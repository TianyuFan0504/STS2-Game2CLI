#!/usr/bin/env python3
from __future__ import annotations

import json
import shlex
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 3

COMBAT_DECISIONS = {"combat_play", "hand_select"}
REWARD_DECISIONS = {
    "card_reward",
    "combat_rewards",
    "event_choice",
    "rest_site",
    "shop",
    "card_select",
    "relic_select",
    "treasure",
}


def summarize_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(state, dict):
        return None
    player = state.get("player") if isinstance(state.get("player"), dict) else {}
    context = state.get("context") if isinstance(state.get("context"), dict) else {}
    return {
        "decision": state.get("decision"),
        "type": state.get("type"),
        "act": context.get("act"),
        "floor": context.get("floor"),
        "ascension": context.get("ascension"),
        "character": player.get("character"),
        "hp": player.get("hp"),
        "max_hp": player.get("max_hp"),
        "gold": player.get("gold"),
    }


class MemoryV2Archive:
    def __init__(self, root: Path):
        self.root = root
        self.runs_root = root / "runs"
        self.archive_dir = root / "archive"
        self.db_path = self.archive_dir / "index.sqlite"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def sync_finished_runs(self) -> None:
        if not self.runs_root.exists():
            return
        for run_dir in sorted(path for path in self.runs_root.iterdir() if path.is_dir()):
            session = self._load_json_dict(run_dir / "data" / "session.json")
            if not session or session.get("ended_at") is None:
                continue
            self.materialize_run(run_dir)

    def materialize_run(self, run_dir: Path) -> None:
        data_dir = run_dir / "data"
        session = self._load_json_dict(data_dir / "session.json")
        if not session or not session.get("run_id") or session.get("ended_at") is None:
            return

        snapshot = self._load_json_dict(data_dir / "state_snapshot.json") or {}
        events = self._load_jsonl(data_dir / "events.jsonl")
        ledger = self._load_jsonl(data_dir / "ledger.jsonl")
        final_state = snapshot.get("normalized_state") if isinstance(snapshot.get("normalized_state"), dict) else {}
        final_summary = snapshot.get("derived_summary") if isinstance(snapshot.get("derived_summary"), dict) else {}

        turns_dir = run_dir / "turns"
        battles_dir = run_dir / "battles"
        rewards_dir = run_dir / "rewards"
        derived_dir = run_dir / "derived"
        for path in (turns_dir, battles_dir, rewards_dir, derived_dir):
            path.mkdir(parents=True, exist_ok=True)

        self._clear_json_dir(turns_dir)
        self._clear_json_dir(battles_dir)
        self._clear_json_dir(rewards_dir)

        turns = self._build_turn_files(turns_dir, session, ledger)
        rewards = self._build_reward_files(rewards_dir, session, turns)
        battles = self._build_battle_files(battles_dir, session, turns)
        deck_timeline = self._build_card_timeline(session, turns, rewards)
        relic_timeline = self._build_relic_timeline(session, turns, rewards)
        route_timeline = self._build_route_timeline(session, final_state)
        resource_timeline = self._build_resource_timeline(session, final_summary, events, turns)
        run_tags = self._build_run_tags(
            session,
            final_summary,
            final_state,
            turns=turns,
            battles=battles,
            rewards=rewards,
            card_events=deck_timeline["events"],
            relic_events=relic_timeline["events"],
        )

        self._write_json(derived_dir / "deck_timeline.json", deck_timeline)
        self._write_json(derived_dir / "relic_timeline.json", relic_timeline)
        self._write_json(derived_dir / "route_timeline.json", route_timeline)
        self._write_json(derived_dir / "resource_timeline.json", resource_timeline)
        self._write_json(
            derived_dir / "run_tags.json",
            {
                "run_id": str(session["run_id"]),
                "tags": run_tags,
            },
        )

        boss_name = self._extract_boss_name(final_state)
        death_enemy = self._extract_death_enemy(final_state)

        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id,
                    started_at,
                    ended_at,
                    character,
                    ascension,
                    seed,
                    result,
                    final_act,
                    final_floor,
                    death_enemy,
                    boss,
                    final_hp,
                    final_gold,
                    summary_path,
                    events_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    started_at = excluded.started_at,
                    ended_at = excluded.ended_at,
                    character = excluded.character,
                    ascension = excluded.ascension,
                    seed = excluded.seed,
                    result = excluded.result,
                    final_act = excluded.final_act,
                    final_floor = excluded.final_floor,
                    death_enemy = excluded.death_enemy,
                    boss = excluded.boss,
                    final_hp = excluded.final_hp,
                    final_gold = excluded.final_gold,
                    summary_path = excluded.summary_path,
                    events_path = excluded.events_path
                """,
                (
                    str(session["run_id"]),
                    session.get("started_at"),
                    session.get("ended_at"),
                    session.get("character"),
                    session.get("ascension"),
                    session.get("seed"),
                    session.get("result"),
                    final_summary.get("act", session.get("latest_act")),
                    final_summary.get("floor", session.get("latest_floor")),
                    death_enemy,
                    boss_name,
                    final_summary.get("hp", session.get("last_hp")),
                    final_summary.get("gold", session.get("last_gold")),
                    str(run_dir / "memory" / "summary.md"),
                    str(data_dir / "events.jsonl"),
                ),
            )
            conn.execute("DELETE FROM run_tags WHERE run_id = ?", (str(session["run_id"]),))
            conn.executemany(
                "INSERT INTO run_tags (run_id, tag_type, tag_value) VALUES (?, ?, ?)",
                [(str(session["run_id"]), tag["tag_type"], tag["tag_value"]) for tag in run_tags],
            )
            conn.execute("DELETE FROM run_cards WHERE run_id = ?", (str(session["run_id"]),))
            conn.executemany(
                """
                INSERT INTO run_cards (
                    run_id,
                    card_id,
                    card_name,
                    op,
                    floor,
                    turn_id,
                    source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(session["run_id"]),
                        event.get("card_id"),
                        event.get("card_name"),
                        event.get("op"),
                        event.get("floor"),
                        event.get("turn_id"),
                        event.get("source"),
                    )
                    for event in deck_timeline["events"]
                ],
            )
            conn.execute("DELETE FROM run_relics WHERE run_id = ?", (str(session["run_id"]),))
            conn.executemany(
                """
                INSERT INTO run_relics (
                    run_id,
                    relic_id,
                    relic_name,
                    op,
                    floor,
                    turn_id,
                    source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(session["run_id"]),
                        event.get("relic_id"),
                        event.get("relic_name"),
                        event.get("op"),
                        event.get("floor"),
                        event.get("turn_id"),
                        event.get("source"),
                    )
                    for event in relic_timeline["events"]
                ],
            )
            conn.execute("DELETE FROM run_battles WHERE run_id = ?", (str(session["run_id"]),))
            conn.executemany(
                """
                INSERT INTO run_battles (
                    run_id,
                    battle_id,
                    act,
                    floor,
                    enemy_signature,
                    hp_before,
                    hp_after,
                    result
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(session["run_id"]),
                        battle["battle_id"],
                        battle.get("act"),
                        battle.get("floor"),
                        battle.get("enemy_signature"),
                        battle.get("hp_before"),
                        battle.get("hp_after"),
                        battle.get("result"),
                    )
                    for battle in battles
                ],
            )
            conn.commit()

    def find_runs(
        self,
        *,
        character: str | None = None,
        result: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT run_id, started_at, ended_at, character, ascension, result, final_act, "
            "final_floor, boss, final_hp, final_gold, summary_path, events_path "
            "FROM runs WHERE 1 = 1"
        )
        params: list[Any] = []
        if character:
            query += " AND character = ?"
            params.append(character)
        if result:
            query += " AND result = ?"
            params.append(result)
        query += " ORDER BY ended_at DESC LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def find_runs_by_tag(self, tag_type: str, tag_value: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT runs.run_id, runs.character, runs.ascension, runs.result, runs.final_act, runs.final_floor
                FROM run_tags
                JOIN runs ON runs.run_id = run_tags.run_id
                WHERE run_tags.tag_type = ? AND run_tags.tag_value = ?
                ORDER BY runs.ended_at DESC
                LIMIT ?
                """,
                (tag_type, tag_value, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def find_battles(self, *, run_id: str | None = None, result: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = (
            "SELECT run_id, battle_id, act, floor, enemy_signature, hp_before, hp_after, result "
            "FROM run_battles WHERE 1 = 1"
        )
        params: list[Any] = []
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        if result:
            query += " AND result = ?"
            params.append(result)
        query += " ORDER BY run_id, battle_id LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def find_card_events(
        self,
        *,
        card_id: str | None = None,
        card_name: str | None = None,
        op: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = "SELECT run_id, card_id, card_name, op, floor, turn_id, source FROM run_cards WHERE 1 = 1"
        params: list[Any] = []
        if card_id:
            query += " AND card_id = ?"
            params.append(card_id)
        if card_name:
            query += " AND card_name = ?"
            params.append(card_name)
        if op:
            query += " AND op = ?"
            params.append(op)
        query += " ORDER BY run_id, floor, turn_id LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def find_relic_events(
        self,
        *,
        relic_id: str | None = None,
        relic_name: str | None = None,
        op: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = "SELECT run_id, relic_id, relic_name, op, floor, turn_id, source FROM run_relics WHERE 1 = 1"
        params: list[Any] = []
        if relic_id:
            query += " AND relic_id = ?"
            params.append(relic_id)
        if relic_name:
            query += " AND relic_name = ?"
            params.append(relic_name)
        if op:
            query += " AND op = ?"
            params.append(op)
        query += " ORDER BY run_id, floor, turn_id LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def _build_turn_files(self, turns_dir: Path, session: dict[str, Any], ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
        turns: list[dict[str, Any]] = []
        current_meta: dict[str, Any] | None = None
        current_records: list[dict[str, Any]] = []

        for record in ledger:
            if self._is_turn_started_record(record):
                if current_meta is not None:
                    turns.append(self._write_turn_file(turns_dir, session, current_meta, current_records))
                current_meta = self._extract_turn_meta(record)
                current_records = [record]
                continue
            if current_meta is not None:
                current_records.append(record)

        if current_meta is not None:
            turns.append(self._write_turn_file(turns_dir, session, current_meta, current_records))
        return turns

    def _write_turn_file(
        self,
        turns_dir: Path,
        session: dict[str, Any],
        meta: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        iteration = int(meta.get("iteration") or (len(list(turns_dir.glob("turn_*.json"))) + 1))
        turn_id = f"turn_{iteration:04d}"
        state_before = self._normalize_summary_dict(meta.get("state_summary"))
        state_before_details = self._normalize_state_details(meta.get("state"))
        state_after = self._reconstruct_turn_end_summary(state_before, records)
        commands = self._extract_turn_commands(records)
        assistant_output = self._extract_turn_assistant_output(records)
        artifact_paths = self._extract_turn_artifact_paths(records)
        summary = assistant_output.strip() if assistant_output else self._summarize_turn(commands, state_before, state_after)

        payload = {
            "turn_id": turn_id,
            "run_id": str(session["run_id"]),
            "iteration": iteration,
            "started_at": records[0].get("ts") if records else None,
            "ended_at": records[-1].get("ts") if records else None,
            "mode": meta.get("mode"),
            "decision_before": state_before.get("decision"),
            "decision_after": state_after.get("decision"),
            "state_before": state_before,
            "state_before_details": state_before_details,
            "state_after": state_after,
            "commands": commands,
            "assistant_output": assistant_output,
            "summary": summary,
            "artifacts": artifact_paths,
            "seq_id_start": records[0].get("seq_id") if records else None,
            "seq_id_end": records[-1].get("seq_id") if records else None,
            "event_count": len(records),
        }
        self._write_json(turns_dir / f"{turn_id}.json", payload)
        return payload

    def _build_reward_files(self, rewards_dir: Path, session: dict[str, Any], turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rewards: list[dict[str, Any]] = []
        for turn in turns:
            source = str(turn.get("decision_before") or "")
            if source not in REWARD_DECISIONS:
                continue
            reward_id = f"reward_{len(rewards) + 1:04d}"
            commands = [command.get("command") for command in turn.get("commands", []) if isinstance(command, dict)]
            options = self._extract_reward_options(turn, source)
            action = self._extract_turn_action(turn, source)
            chosen_option = self._resolve_action_option(action, options)
            skipped = self._action_is_skip(action)
            reward = {
                "reward_id": reward_id,
                "run_id": str(session["run_id"]),
                "turn_id": turn.get("turn_id"),
                "act": turn.get("state_before", {}).get("act") or turn.get("state_after", {}).get("act"),
                "floor": turn.get("state_before", {}).get("floor") or turn.get("state_after", {}).get("floor"),
                "source": source,
                "options": options,
                "chosen": chosen_option,
                "chosen_command": None if action is None else action.get("command"),
                "skipped": skipped,
                "commands": commands,
                "decision_after": turn.get("decision_after"),
                "notes": "Phase-2 reward extraction includes parsed options and chosen option when turn state has enough detail.",
            }
            self._write_json(rewards_dir / f"{reward_id}.json", reward)
            rewards.append(reward)
        return rewards

    def _build_battle_files(self, battles_dir: Path, session: dict[str, Any], turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        battles: list[dict[str, Any]] = []
        current_group: list[dict[str, Any]] = []

        for turn in turns:
            if self._turn_is_combat(turn):
                current_group.append(turn)
                continue
            if current_group:
                battles.append(self._write_battle_file(battles_dir, session, current_group, len(battles) + 1))
                current_group = []
        if current_group:
            battles.append(self._write_battle_file(battles_dir, session, current_group, len(battles) + 1))
        return battles

    def _write_battle_file(
        self,
        battles_dir: Path,
        session: dict[str, Any],
        turns: list[dict[str, Any]],
        index: int,
    ) -> dict[str, Any]:
        last = turns[-1]
        battle_detail_state = self._select_battle_detail_state(turns)
        battle_start_state = self._select_battle_entry_state(turns[0])
        enemies = battle_detail_state.get("enemies") if isinstance(battle_detail_state.get("enemies"), list) else []
        enemy_names = [str(enemy.get("name")) for enemy in enemies if isinstance(enemy, dict) and enemy.get("name")]
        commands = [
            command.get("command")
            for turn in turns
            for command in turn.get("commands", [])
            if isinstance(command, dict)
        ]
        battle = {
            "battle_id": f"battle_{index:04d}",
            "run_id": str(session["run_id"]),
            "act": battle_detail_state.get("context", {}).get("act", battle_start_state.get("act"))
            if isinstance(battle_detail_state.get("context"), dict)
            else battle_start_state.get("act"),
            "floor": battle_detail_state.get("context", {}).get("floor", battle_start_state.get("floor"))
            if isinstance(battle_detail_state.get("context"), dict)
            else battle_start_state.get("floor"),
            "room_type": battle_detail_state.get("room_type"),
            "enemy_names": enemy_names,
            "enemy_signature": self._build_enemy_signature(enemies),
            "hp_before": battle_start_state.get("hp"),
            "hp_after": last.get("state_after", {}).get("hp"),
            "turn_count": len(turns),
            "result": self._infer_battle_result(turns, session),
            "turn_ids": [turn.get("turn_id") for turn in turns],
            "commands": commands,
            "notes": "Phase-1 battle extraction groups contiguous combat turns from turn summaries.",
        }
        self._write_json(battles_dir / f"{battle['battle_id']}.json", battle)
        return battle

    def _select_battle_entry_state(self, turn: dict[str, Any]) -> dict[str, Any]:
        before_details = turn.get("state_before_details", {}) if isinstance(turn.get("state_before_details"), dict) else {}
        before = turn.get("state_before", {}) if isinstance(turn.get("state_before"), dict) else {}
        after = turn.get("state_after", {}) if isinstance(turn.get("state_after"), dict) else {}
        if str(turn.get("decision_before") or "") in COMBAT_DECISIONS:
            if before_details:
                return self._summary_from_state_details(before_details)
            return before
        if str(turn.get("decision_after") or "") in COMBAT_DECISIONS:
            return after
        return before or after

    def _select_battle_detail_state(self, turns: list[dict[str, Any]]) -> dict[str, Any]:
        for turn in turns:
            if str(turn.get("decision_before") or "") in COMBAT_DECISIONS:
                details = turn.get("state_before_details")
                if isinstance(details, dict) and details:
                    return details
        first = turns[0]
        details = first.get("state_before_details")
        if isinstance(details, dict):
            return details
        return {}

    def _build_route_timeline(self, session: dict[str, Any], final_state: dict[str, Any]) -> dict[str, Any]:
        visited = final_state.get("visited")
        if not isinstance(visited, list) or not visited:
            visited = session.get("route_history")
        entries: list[dict[str, Any]] = []
        if isinstance(visited, list):
            for index, entry in enumerate(visited):
                if not isinstance(entry, dict):
                    continue
                entries.append(
                    {
                        "index": index,
                        "col": entry.get("col"),
                        "row": entry.get("row"),
                        "type": entry.get("type"),
                    }
                )
        return {
            "run_id": str(session["run_id"]),
            "source": "state.visited" if isinstance(final_state.get("visited"), list) and final_state.get("visited") else "session.route_history",
            "entries": entries,
        }

    def _build_resource_timeline(
        self,
        session: dict[str, Any],
        final_summary: dict[str, Any],
        events: list[dict[str, Any]],
        turns: list[dict[str, Any]],
    ) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("event_type") or "")
            if event_type not in {"hp_change", "gold_change", "floor_change", "act_change"}:
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            entry: dict[str, Any] = {
                "seq_id": event.get("seq_id"),
                "ts": event.get("ts"),
                "event_type": event_type,
                "act": event.get("act"),
                "floor": event.get("floor"),
                "decision": event.get("decision"),
                "text": event.get("text"),
                "from": payload.get("from"),
                "to": payload.get("to"),
            }
            if event_type == "hp_change":
                before = payload.get("from")
                after = payload.get("to")
                if isinstance(before, list) and len(before) == 2 and isinstance(after, list) and len(after) == 2:
                    if isinstance(before[0], (int, float)) and isinstance(after[0], (int, float)):
                        entry["delta"] = int(after[0] - before[0])
            elif event_type == "gold_change":
                before = payload.get("from")
                after = payload.get("to")
                if isinstance(before, (int, float)) and isinstance(after, (int, float)):
                    entry["delta"] = int(after - before)
            entries.append(entry)

        return {
            "run_id": str(session["run_id"]),
            "entries": entries,
            "turn_count": len(turns),
            "final": {
                "act": final_summary.get("act", session.get("latest_act")),
                "floor": final_summary.get("floor", session.get("latest_floor")),
                "hp": final_summary.get("hp", session.get("last_hp")),
                "max_hp": final_summary.get("max_hp", session.get("last_max_hp")),
                "gold": final_summary.get("gold", session.get("last_gold")),
                "result": session.get("result"),
            },
        }

    def _build_card_timeline(
        self,
        session: dict[str, Any],
        turns: list[dict[str, Any]],
        rewards: list[dict[str, Any]],
    ) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        reward_by_turn = {str(reward.get("turn_id") or ""): reward for reward in rewards}

        for turn in turns:
            turn_id = str(turn.get("turn_id") or "")
            reward = reward_by_turn.get(turn_id)
            if reward is not None:
                source = str(reward.get("source") or "")
                chosen = reward.get("chosen")
                if source == "card_reward":
                    event = self._card_event_from_option(turn, chosen, op="add", source="card_reward")
                    if event is not None:
                        events.append(event)
                elif source == "shop" and isinstance(chosen, dict) and chosen.get("category") == "card":
                    event = self._card_event_from_option(turn, chosen, op="add", source="shop")
                    if event is not None:
                        events.append(event)
                elif source == "combat_rewards" and isinstance(chosen, dict) and str(chosen.get("type") or "") in {"card", "special_card"}:
                    event = self._card_event_from_option(turn, chosen, op="add", source="combat_rewards")
                    if event is not None:
                        events.append(event)
                elif source == "card_select":
                    op = self._infer_card_select_operation(turn)
                    event = self._card_event_from_option(turn, chosen, op=op, source="card_select")
                    if event is not None:
                        events.append(event)

        return {
            "run_id": str(session["run_id"]),
            "mode": "delta",
            "events": events,
            "summary": self._summarize_delta_events(events, key_name="card_name"),
        }

    def _build_relic_timeline(
        self,
        session: dict[str, Any],
        turns: list[dict[str, Any]],
        rewards: list[dict[str, Any]],
    ) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        reward_by_turn = {str(reward.get("turn_id") or ""): reward for reward in rewards}

        for turn in turns:
            turn_id = str(turn.get("turn_id") or "")
            reward = reward_by_turn.get(turn_id)
            if reward is None:
                continue
            source = str(reward.get("source") or "")
            chosen = reward.get("chosen")
            if source == "shop" and isinstance(chosen, dict) and chosen.get("category") == "relic":
                event = self._relic_event_from_option(turn, chosen, op="add", source="shop")
                if event is not None:
                    events.append(event)
            elif source in {"treasure", "relic_select"}:
                event = self._relic_event_from_option(turn, chosen, op="add", source=source)
                if event is not None:
                    events.append(event)
            elif source == "event_choice":
                event = self._relic_event_from_option(turn, chosen, op="add", source="event_choice")
                if event is not None:
                    events.append(event)
            elif source == "combat_rewards" and isinstance(chosen, dict) and str(chosen.get("type") or "") == "relic":
                event = self._relic_event_from_option(turn, chosen, op="add", source="combat_rewards")
                if event is not None:
                    events.append(event)

        return {
            "run_id": str(session["run_id"]),
            "mode": "delta",
            "events": events,
            "summary": self._summarize_delta_events(events, key_name="relic_name"),
        }

    def _build_run_tags(
        self,
        session: dict[str, Any],
        final_summary: dict[str, Any],
        final_state: dict[str, Any],
        *,
        turns: list[dict[str, Any]],
        battles: list[dict[str, Any]],
        rewards: list[dict[str, Any]],
        card_events: list[dict[str, Any]],
        relic_events: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        seen: set[tuple[str, str]] = set()
        tags: list[dict[str, str]] = []

        def add(tag_type: str, value: Any) -> None:
            if value in {None, ""}:
                return
            tag_value = str(value)
            key = (tag_type, tag_value)
            if key in seen:
                return
            seen.add(key)
            tags.append({"tag_type": tag_type, "tag_value": tag_value})

        add("character", session.get("character"))
        add("result", session.get("result"))
        add("ascension", session.get("ascension"))
        add("final_act", final_summary.get("act", session.get("latest_act")))
        add("final_floor", final_summary.get("floor", session.get("latest_floor")))
        add("latest_decision", session.get("latest_decision"))
        add("boss", self._extract_boss_name(final_state))
        add("death_enemy", self._extract_death_enemy(final_state))
        add("turn_count", len(turns))
        add("battle_count", len(battles))
        add("reward_count", len(rewards))
        add("card_event_count", len(card_events))
        add("relic_event_count", len(relic_events))
        return tags

    def _extract_boss_name(self, final_state: dict[str, Any]) -> str | None:
        boss = final_state.get("boss")
        if isinstance(boss, dict):
            for key in ("name", "id"):
                value = boss.get(key)
                if value:
                    return str(value)
        nested_map = final_state.get("map")
        if isinstance(nested_map, dict):
            nested_boss = nested_map.get("boss")
            if isinstance(nested_boss, dict):
                for key in ("name", "id"):
                    value = nested_boss.get(key)
                    if value:
                        return str(value)
        return None

    def _extract_death_enemy(self, final_state: dict[str, Any]) -> str | None:
        game_over = final_state.get("game_over")
        if not isinstance(game_over, dict):
            return None
        for key in ("death_enemy", "killed_by", "enemy_name"):
            value = game_over.get(key)
            if value:
                return str(value)
        return None

    def _normalize_state_details(self, value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    def _normalize_summary_dict(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {
            "decision": value.get("decision"),
            "type": value.get("type"),
            "act": value.get("act"),
            "floor": value.get("floor"),
            "ascension": value.get("ascension"),
            "character": value.get("character"),
            "hp": value.get("hp"),
            "max_hp": value.get("max_hp"),
            "gold": value.get("gold"),
        }

    def _summary_from_state_details(self, state: dict[str, Any]) -> dict[str, Any]:
        summary = summarize_state(state)
        return summary or {}

    def _is_turn_started_record(self, record: dict[str, Any]) -> bool:
        return str(record.get("record_type") or "") == "artifact" and str(record.get("artifact_type") or "") == "turn_started"

    def _extract_turn_meta(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        return {
            "iteration": payload.get("iteration"),
            "mode": payload.get("mode"),
            "state_summary": self._normalize_summary_dict(payload.get("state_summary")),
            "state": self._normalize_state_details(payload.get("state")),
        }

    def _reconstruct_turn_end_summary(self, state_before: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
        current = dict(state_before)
        for record in records:
            current = self._apply_record_to_summary(current, record)
        return current

    def _apply_record_to_summary(self, current: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        summary = dict(current)
        if not summary:
            summary = self._seed_summary_from_record(record)

        if record.get("act") is not None:
            summary["act"] = record.get("act")
        if record.get("floor") is not None:
            summary["floor"] = record.get("floor")
        if record.get("decision") is not None:
            summary["decision"] = record.get("decision")

        if str(record.get("record_type") or "") != "event":
            return summary

        event_type = str(record.get("event_type") or "")
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}

        if event_type == "run_started":
            started_summary = self._normalize_summary_dict(payload.get("summary"))
            if started_summary:
                summary.update(started_summary)
        elif event_type == "state_transition":
            summary["decision"] = payload.get("to", summary.get("decision"))
        elif event_type == "act_change":
            summary["act"] = payload.get("to", summary.get("act"))
        elif event_type == "floor_change":
            summary["floor"] = payload.get("to", summary.get("floor"))
        elif event_type == "gold_change":
            summary["gold"] = payload.get("to", summary.get("gold"))
        elif event_type == "hp_change":
            after = payload.get("to")
            if isinstance(after, list) and len(after) == 2:
                summary["hp"] = after[0]
                summary["max_hp"] = after[1]
        return summary

    def _seed_summary_from_record(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if str(record.get("record_type") or "") == "event" and str(record.get("event_type") or "") == "run_started":
            summary = self._normalize_summary_dict(payload.get("summary"))
            if summary:
                return summary
        return {
            "decision": record.get("decision"),
            "type": None,
            "act": record.get("act"),
            "floor": record.get("floor"),
            "ascension": None,
            "character": None,
            "hp": None,
            "max_hp": None,
            "gold": None,
        }

    def _extract_turn_commands(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        commands: list[dict[str, Any]] = []
        for record in records:
            if str(record.get("record_type") or "") != "event" or str(record.get("event_type") or "") != "sts2_command":
                continue
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            command = payload.get("command")
            if not isinstance(command, str) or not command.strip():
                continue
            commands.append(
                {
                    "command": command,
                    "source": payload.get("source"),
                    "result": payload.get("result"),
                    "seq_id": record.get("seq_id"),
                    "ts": record.get("ts"),
                }
            )
        return commands

    def _extract_turn_assistant_output(self, records: list[dict[str, Any]]) -> str:
        assistant_done = ""
        assistant_delta_parts: list[str] = []
        for record in records:
            if str(record.get("record_type") or "") != "agent_event":
                continue
            kind = str(record.get("kind") or "")
            text = str(record.get("text") or "")
            if kind == "assistant_done" and text:
                assistant_done = text
            elif kind == "assistant_text_delta" and text:
                assistant_delta_parts.append(text)
        if assistant_done:
            return assistant_done
        return "".join(assistant_delta_parts).strip()

    def _extract_turn_artifact_paths(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        paths: dict[str, Any] = {
            "runtime_prompt": None,
            "raw_log": None,
            "text_log": None,
        }
        for record in records:
            if str(record.get("record_type") or "") != "artifact":
                continue
            artifact_type = str(record.get("artifact_type") or "")
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            if artifact_type == "runtime_prompt":
                paths["runtime_prompt"] = payload.get("path")
            elif artifact_type == "iteration_artifacts":
                paths["raw_log"] = payload.get("raw_path")
                paths["text_log"] = payload.get("text_path")
        return paths

    def _extract_reward_options(self, turn: dict[str, Any], source: str) -> list[dict[str, Any]]:
        details = turn.get("state_before_details", {}) if isinstance(turn.get("state_before_details"), dict) else {}
        if source == "card_reward":
            return self._clone_option_list(details.get("cards"))
        if source == "combat_rewards":
            return self._clone_option_list(details.get("items"))
        if source == "event_choice":
            return self._clone_option_list(details.get("options"))
        if source == "rest_site":
            return self._clone_option_list(details.get("options"))
        if source == "shop":
            options = self._clone_option_list(details.get("items"))
            card_removal = details.get("card_removal")
            if isinstance(card_removal, dict):
                options.append(dict(card_removal))
            return options
        if source == "card_select":
            return self._clone_option_list(details.get("cards"))
        if source == "relic_select":
            return self._clone_option_list(details.get("relics"))
        if source == "treasure":
            return self._clone_option_list(details.get("relics"))
        return []

    def _clone_option_list(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, dict)]

    def _extract_turn_action(self, turn: dict[str, Any], source: str) -> dict[str, Any] | None:
        commands = turn.get("commands", [])
        if not isinstance(commands, list):
            return None

        preferred_by_source = {
            "card_reward": {"pick-card-reward", "skip-card-reward"},
            "combat_rewards": {"claim-reward", "proceed"},
            "event_choice": {"event", "advance-dialogue", "proceed"},
            "rest_site": {"rest", "proceed"},
            "shop": {"shop-buy", "proceed"},
            "card_select": {"select-card", "confirm-selection", "cancel-selection"},
            "relic_select": {"select-relic", "skip-relic-selection"},
            "treasure": {"claim-treasure-relic", "proceed"},
        }
        preferred = preferred_by_source.get(source, set())

        parsed_commands = [self._parse_turn_command(command) for command in commands if isinstance(command, dict)]
        parsed_commands = [command for command in parsed_commands if command is not None]
        for command in parsed_commands:
            if str(command.get("name") or "") in preferred:
                return command
        return parsed_commands[0] if parsed_commands else None

    def _parse_turn_command(self, command: dict[str, Any]) -> dict[str, Any] | None:
        command_text = command.get("command")
        if not isinstance(command_text, str) or not command_text.strip():
            return None
        try:
            tokens = shlex.split(command_text)
        except ValueError:
            tokens = command_text.strip().split()
        if not tokens:
            return None
        index: int | None = None
        if len(tokens) > 1:
            try:
                index = int(tokens[1])
            except ValueError:
                index = None
        return {
            "command": command_text,
            "name": tokens[0],
            "index": index,
        }

    def _resolve_action_option(self, action: dict[str, Any] | None, options: list[dict[str, Any]]) -> dict[str, Any] | None:
        if action is None or not options:
            return None
        index = action.get("index")
        if isinstance(index, int):
            for option in options:
                if option.get("index") == index:
                    return dict(option)
            if 0 <= index < len(options):
                return dict(options[index])
        return None

    def _action_is_skip(self, action: dict[str, Any] | None) -> bool:
        if action is None:
            return False
        return str(action.get("name") or "") in {
            "skip-card-reward",
            "skip-relic-selection",
            "cancel-selection",
        }

    def _card_event_from_option(
        self,
        turn: dict[str, Any],
        option: Any,
        *,
        op: str | None,
        source: str,
    ) -> dict[str, Any] | None:
        if not isinstance(option, dict) or not op:
            return None
        card_id = option.get("id") or option.get("card_id")
        card_name = option.get("name") or option.get("card_name")
        if card_name in {None, ""} and card_id in {None, ""}:
            return None
        return {
            "turn_id": turn.get("turn_id"),
            "source": source,
            "op": op,
            "floor": turn.get("state_before", {}).get("floor") or turn.get("state_after", {}).get("floor"),
            "card_id": None if card_id in {None, ""} else str(card_id),
            "card_name": str(card_name or card_id),
        }

    def _relic_event_from_option(
        self,
        turn: dict[str, Any],
        option: Any,
        *,
        op: str | None,
        source: str,
    ) -> dict[str, Any] | None:
        if not isinstance(option, dict) or not op:
            return None
        relic_id = option.get("id") or option.get("relic_id")
        relic_name = option.get("name") or option.get("relic_name")
        if relic_name in {None, ""} and relic_id in {None, ""}:
            return None
        return {
            "turn_id": turn.get("turn_id"),
            "source": source,
            "op": op,
            "floor": turn.get("state_before", {}).get("floor") or turn.get("state_after", {}).get("floor"),
            "relic_id": None if relic_id in {None, ""} else str(relic_id),
            "relic_name": str(relic_name or relic_id),
        }

    def _infer_card_select_operation(self, turn: dict[str, Any]) -> str | None:
        details = turn.get("state_before_details", {}) if isinstance(turn.get("state_before_details"), dict) else {}
        screen_type = str(details.get("screen_type") or "").strip().lower()
        prompt = str(details.get("prompt") or "").strip().lower()
        if screen_type == "upgrade" or "upgrade" in prompt:
            return "upgrade"
        if screen_type == "transform" or "transform" in prompt:
            return "transform"
        if "remove" in prompt or "purge" in prompt or "delete" in prompt:
            return "remove"
        if "duplicate" in prompt or "copy" in prompt:
            return "duplicate"
        return None

    def _summarize_delta_events(self, events: list[dict[str, Any]], *, key_name: str) -> dict[str, Any]:
        op_counts: dict[str, int] = {}
        names: list[str] = []
        for event in events:
            op = str(event.get("op") or "unknown")
            op_counts[op] = op_counts.get(op, 0) + 1
            name = event.get(key_name)
            if isinstance(name, str) and name and name not in names:
                names.append(name)
        return {
            "event_count": len(events),
            "op_counts": op_counts,
            "names": names,
        }

    def _build_enemy_signature(self, enemies: list[dict[str, Any]]) -> str | None:
        if not enemies:
            return None
        parts: list[str] = []
        for enemy in enemies:
            if not isinstance(enemy, dict):
                continue
            enemy_id = enemy.get("entity_id") or enemy.get("name")
            if enemy_id:
                parts.append(str(enemy_id))
        if not parts:
            return None
        return "|".join(parts)

    def _summarize_turn(self, commands: list[dict[str, Any]], state_before: dict[str, Any], state_after: dict[str, Any]) -> str:
        if commands:
            command_text = ", ".join(str(command.get("command") or "") for command in commands if command.get("command"))
            after = state_after.get("decision") or state_before.get("decision") or "unknown"
            return f"Executed {command_text} and ended on {after}."
        before = state_before.get("decision") or "unknown"
        after = state_after.get("decision") or "unknown"
        if before == after:
            return f"Observed {before} without executing a state-changing command."
        return f"Observed transition from {before} to {after}."

    def _turn_is_combat(self, turn: dict[str, Any]) -> bool:
        before = str(turn.get("decision_before") or "")
        after = str(turn.get("decision_after") or "")
        return before in COMBAT_DECISIONS or after in COMBAT_DECISIONS

    def _infer_battle_result(self, turns: list[dict[str, Any]], session: dict[str, Any]) -> str:
        final_decision = str(turns[-1].get("decision_after") or "")
        if final_decision == "combat_rewards":
            return "won"
        if final_decision == "game_over" or session.get("result") == "lost":
            return "lost"
        if final_decision and final_decision not in COMBAT_DECISIONS:
            return "finished"
        return "ongoing"

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT,
                    ended_at TEXT,
                    character TEXT,
                    ascension INTEGER,
                    seed TEXT,
                    result TEXT,
                    final_act INTEGER,
                    final_floor INTEGER,
                    death_enemy TEXT,
                    boss TEXT,
                    final_hp INTEGER,
                    final_gold INTEGER,
                    summary_path TEXT NOT NULL,
                    events_path TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_tags (
                    run_id TEXT NOT NULL,
                    tag_type TEXT NOT NULL,
                    tag_value TEXT NOT NULL,
                    PRIMARY KEY (run_id, tag_type, tag_value),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_battles (
                    run_id TEXT NOT NULL,
                    battle_id TEXT NOT NULL,
                    act INTEGER,
                    floor INTEGER,
                    enemy_signature TEXT,
                    hp_before INTEGER,
                    hp_after INTEGER,
                    result TEXT,
                    PRIMARY KEY (run_id, battle_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_cards (
                    run_id TEXT NOT NULL,
                    card_id TEXT,
                    card_name TEXT NOT NULL,
                    op TEXT NOT NULL,
                    floor INTEGER,
                    turn_id TEXT,
                    source TEXT,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_relics (
                    run_id TEXT NOT NULL,
                    relic_id TEXT,
                    relic_name TEXT NOT NULL,
                    op TEXT NOT NULL,
                    floor INTEGER,
                    turn_id TEXT,
                    source TEXT,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_character_ascension ON runs(character, ascension)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_result ON runs(result)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_ended_at ON runs(ended_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_run_tags_lookup ON run_tags(tag_type, tag_value)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_run_battles_floor ON run_battles(floor)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_run_cards_card_id ON run_cards(card_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_run_cards_card_name ON run_cards(card_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_run_relics_relic_id ON run_relics(relic_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_run_relics_relic_name ON run_relics(relic_name)")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _clear_json_dir(self, path: Path) -> None:
        for child in path.glob("*.json"):
            child.unlink()

    def _load_json_dict(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _load_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                data = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                rows.append(data)
        return rows
