#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2

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
        route_timeline = self._build_route_timeline(session, final_state)
        resource_timeline = self._build_resource_timeline(session, final_summary, events, turns)
        run_tags = self._build_run_tags(session, final_summary, final_state, turns=turns, battles=battles, rewards=rewards)

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

        with self._connect() as conn:
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
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def find_runs_by_tag(self, tag_type: str, tag_value: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
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
        with self._connect() as conn:
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
            chosen = commands[0] if commands else None
            skipped = any(
                isinstance(command, str) and (
                    command.startswith("skip-")
                    or command.startswith("skip ")
                    or command.startswith("skip-card-reward")
                    or command.startswith("skip-relic-selection")
                )
                for command in commands
            )
            reward = {
                "reward_id": reward_id,
                "run_id": str(session["run_id"]),
                "turn_id": turn.get("turn_id"),
                "act": turn.get("state_before", {}).get("act") or turn.get("state_after", {}).get("act"),
                "floor": turn.get("state_before", {}).get("floor") or turn.get("state_after", {}).get("floor"),
                "source": source,
                "options": [],
                "chosen": chosen,
                "skipped": skipped,
                "commands": commands,
                "decision_after": turn.get("decision_after"),
                "notes": "Phase-1 reward extraction stores command-level decisions; option payloads are not yet reconstructed.",
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
        first = turns[0]
        last = turns[-1]
        battle_start_state = self._select_battle_entry_state(first)
        commands = [
            command.get("command")
            for turn in turns
            for command in turn.get("commands", [])
            if isinstance(command, dict)
        ]
        battle = {
            "battle_id": f"battle_{index:04d}",
            "run_id": str(session["run_id"]),
            "act": battle_start_state.get("act"),
            "floor": battle_start_state.get("floor"),
            "room_type": None,
            "enemy_names": [],
            "enemy_signature": None,
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
        before = turn.get("state_before", {}) if isinstance(turn.get("state_before"), dict) else {}
        after = turn.get("state_after", {}) if isinstance(turn.get("state_after"), dict) else {}
        if str(turn.get("decision_before") or "") in COMBAT_DECISIONS:
            return before
        if str(turn.get("decision_after") or "") in COMBAT_DECISIONS:
            return after
        return before or after

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

    def _build_run_tags(
        self,
        session: dict[str, Any],
        final_summary: dict[str, Any],
        final_state: dict[str, Any],
        *,
        turns: list[dict[str, Any]],
        battles: list[dict[str, Any]],
        rewards: list[dict[str, Any]],
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

    def _is_turn_started_record(self, record: dict[str, Any]) -> bool:
        return str(record.get("record_type") or "") == "artifact" and str(record.get("artifact_type") or "") == "turn_started"

    def _extract_turn_meta(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        return {
            "iteration": payload.get("iteration"),
            "mode": payload.get("mode"),
            "state_summary": self._normalize_summary_dict(payload.get("state_summary")),
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
        with self._connect() as conn:
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_character_ascension ON runs(character, ascension)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_result ON runs(result)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_ended_at ON runs(ended_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_run_tags_lookup ON run_tags(tag_type, tag_value)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_run_battles_floor ON run_battles(floor)")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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
