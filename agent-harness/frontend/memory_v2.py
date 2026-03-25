#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


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
        final_state = snapshot.get("normalized_state") if isinstance(snapshot.get("normalized_state"), dict) else {}
        final_summary = snapshot.get("derived_summary") if isinstance(snapshot.get("derived_summary"), dict) else {}

        turns_dir = run_dir / "turns"
        battles_dir = run_dir / "battles"
        rewards_dir = run_dir / "rewards"
        derived_dir = run_dir / "derived"
        for path in (turns_dir, battles_dir, rewards_dir, derived_dir):
            path.mkdir(parents=True, exist_ok=True)

        route_timeline = self._build_route_timeline(session, final_state)
        resource_timeline = self._build_resource_timeline(session, final_summary, events)
        run_tags = self._build_run_tags(session, final_summary, final_state)

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
                [
                    (str(session["run_id"]), tag["tag_type"], tag["tag_value"])
                    for tag in run_tags
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
                "CREATE INDEX IF NOT EXISTS idx_runs_character_ascension ON runs(character, ascension)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_result ON runs(result)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_ended_at ON runs(ended_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_run_tags_lookup ON run_tags(tag_type, tag_value)")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
