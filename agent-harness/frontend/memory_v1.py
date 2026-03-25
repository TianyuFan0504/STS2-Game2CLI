#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_v2 import MemoryV2Archive
from sts2_commands import extract_sts2_segments


def summarize_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not state:
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


@dataclass
class RunMemory:
    run_id: str
    run_dir: Path
    memory_dir: Path
    data_dir: Path
    seq_counter: int = 0
    recent_commands: deque[str] = field(default_factory=lambda: deque(maxlen=20))
    recent_state_changes: deque[str] = field(default_factory=lambda: deque(maxlen=30))
    latest_summary: dict[str, Any] | None = None
    latest_state: dict[str, Any] | None = None
    session_data: dict[str, Any] = field(default_factory=dict)


class MemoryV1Store:
    def __init__(self, root: Path):
        self.root = root
        self.runs_root = root / "runs"
        self.latest_link = root / "latest"
        self.root.mkdir(parents=True, exist_ok=True)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.v2 = MemoryV2Archive(root)
        self.active: RunMemory | None = None
        self.last_run_dir: Path | None = None
        self.pending_new_run: dict[str, Any] | None = None
        self.pending_run_command: dict[str, Any] | None = None
        self.pending_turn_start: dict[str, Any] | None = None
        self._restore_from_disk()
        self.v2.sync_finished_runs()

    def _restore_from_disk(self) -> None:
        run_dir = self._resolve_latest_run_dir()
        if run_dir is None:
            return

        memory_dir = run_dir / "memory"
        data_dir = run_dir / "data"
        session = self._load_json_dict(data_dir / "session.json")
        snapshot = self._load_json_dict(data_dir / "state_snapshot.json")
        if session is None or not memory_dir.is_dir() or not data_dir.is_dir():
            return

        self.last_run_dir = run_dir
        if not self._session_is_active(session):
            return

        latest_summary = snapshot.get("derived_summary") if isinstance(snapshot.get("derived_summary"), dict) else None
        latest_state = snapshot.get("normalized_state") if isinstance(snapshot.get("normalized_state"), dict) else None
        restored = RunMemory(
            run_id=run_dir.name,
            run_dir=run_dir,
            memory_dir=memory_dir,
            data_dir=data_dir,
            seq_counter=self._restore_seq_counter(session, data_dir),
            latest_summary=latest_summary,
            latest_state=latest_state,
            session_data=session,
        )
        self._restore_recent_views(restored)
        self.active = restored

    def _resolve_latest_run_dir(self) -> Path | None:
        latest_target: Path | None = None
        if self.latest_link.is_symlink() or self.latest_link.exists():
            try:
                latest_target = self.latest_link.resolve(strict=True)
            except OSError:
                latest_target = None
        if latest_target is not None and latest_target.is_dir():
            return latest_target

        run_dirs = sorted(path for path in self.runs_root.iterdir() if path.is_dir())
        return run_dirs[-1] if run_dirs else None

    def _load_json_dict(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _session_is_active(self, session: dict[str, Any]) -> bool:
        status = str(session.get("status") or "").strip().lower()
        if status:
            return status == "active"
        return session.get("ended_at") is None

    def _restore_seq_counter(self, session: dict[str, Any], data_dir: Path) -> int:
        seq_id = session.get("latest_seq_id")
        if isinstance(seq_id, int):
            return seq_id
        if isinstance(seq_id, str):
            try:
                return int(seq_id)
            except ValueError:
                pass

        ledger_path = data_dir / "ledger.jsonl"
        if not ledger_path.exists():
            return 0

        last_seq = 0
        for raw_line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and isinstance(record.get("seq_id"), int):
                last_seq = record["seq_id"]
        return last_seq

    def _restore_recent_views(self, run_memory: RunMemory) -> None:
        events_path = run_memory.data_dir / "events.jsonl"
        if not events_path.exists():
            return

        for raw_line in events_path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue

            event_type = str(record.get("event_type") or "")
            if event_type == "sts2_command":
                payload = record.get("payload")
                command = None
                if isinstance(payload, dict) and isinstance(payload.get("command"), str):
                    command = payload.get("command")
                elif isinstance(record.get("text"), str):
                    command = record.get("text")
                if command:
                    run_memory.recent_commands.append(command)

            if event_type in {"state_transition", "hp_change", "floor_change", "gold_change", "act_change"}:
                ts = str(record.get("ts") or "")
                time_label = ts[11:19] if len(ts) >= 19 else "--:--:--"
                text = str(record.get("text") or "")
                run_memory.recent_state_changes.appendleft(f"{time_label} [{event_type}] {text}")

    def get_prompt_context(self) -> str:
        if self.active is None:
            return ""
        summary_path = self.active.memory_dir / "summary.md"
        if not summary_path.exists():
            return ""
        return summary_path.read_text(encoding="utf-8").strip()

    def get_visible_summary(self) -> dict[str, Any] | None:
        active_info = self.get_active_run_info()
        if active_info is not None:
            summary_path = Path(active_info["memory_dir"]) / "summary.md"
            if summary_path.exists():
                return {
                    "run_id": active_info["run_id"],
                    "path": str(summary_path),
                    "source": "active",
                    "content": summary_path.read_text(encoding="utf-8"),
                }

        last_info = self.get_last_run_info()
        if last_info is not None:
            summary_path = Path(last_info["memory_dir"]) / "summary.md"
            if summary_path.exists():
                return {
                    "run_id": last_info["run_id"],
                    "path": str(summary_path),
                    "source": "last",
                    "content": summary_path.read_text(encoding="utf-8"),
                }

        return None

    def get_active_run_info(self) -> dict[str, Any] | None:
        if self.active is None:
            return None
        return {
            "run_id": self.active.run_id,
            "run_dir": str(self.active.run_dir),
            "memory_dir": str(self.active.memory_dir),
            "data_dir": str(self.active.data_dir),
            "ledger_path": str(self.active.data_dir / "ledger.jsonl"),
            "iterations_dir": str(self.active.data_dir / "iterations"),
            "runtime_prompt_path": str(self.active.data_dir / "runtime_prompt.md"),
        }

    def get_last_run_info(self) -> dict[str, Any] | None:
        if self.last_run_dir is None:
            return None
        return {
            "run_id": self.last_run_dir.name,
            "run_dir": str(self.last_run_dir),
            "memory_dir": str(self.last_run_dir / "memory"),
            "data_dir": str(self.last_run_dir / "data"),
        }

    def get_active_iteration_dir(self, iteration: int) -> Path | None:
        if self.active is None:
            return None
        return self.active.data_dir / "iterations" / f"{iteration:04d}"

    def record_state(
        self,
        state: dict[str, Any] | None,
        *,
        raw_state: dict[str, Any] | None = None,
        source: str = "system",
    ) -> None:
        summary = summarize_state(state)
        if summary is None:
            return

        if self.active is not None and self.pending_new_run is not None and self._should_split_on_new_state(summary):
            result = self._infer_result(self.active.latest_summary or {}, previous_state=self.active.latest_state, session=self.active.session_data)
            self._finalize_run(result)

        if self.active is None:
            if summary.get("decision") != "menu":
                self._start_run(self._merge_summary_with_pending(summary), prime_summary=False)
            else:
                return

        previous_summary = self.active.latest_summary
        previous_state = self.active.latest_state
        self.active.latest_summary = summary
        self.active.latest_state = state
        self._update_session_from_summary(summary, state=state, source=source)
        self._write_state_snapshot(state, raw_state, summary)

        if previous_summary is None:
            self._flush_pending_turn_start(summary)
            self._flush_pending_run_command()
            payload: dict[str, Any] = {"source": source, "summary": summary}
            if self.pending_new_run is not None:
                payload["command"] = self.pending_new_run.get("command")
                payload["command_source"] = self.pending_new_run.get("source")
            self._append_event("run_started", f"Run started ({source})", payload)
            self.pending_new_run = None
            self._write_summary()
            return

        changes = self._diff_summary(previous_summary, summary)
        for event_type, text, payload in changes:
            self._append_event(event_type, text, payload)
            self.active.recent_state_changes.appendleft(f"{time.strftime('%H:%M:%S')} [{event_type}] {text}")

        self._write_summary()

        if self._should_finalize_on_menu_state(
            previous_summary=previous_summary,
            previous_state=previous_state,
            current_summary=summary,
            current_state=state,
        ):
            result = self._infer_result(
                summary,
                current_state=state,
                previous_summary=previous_summary,
                previous_state=previous_state,
                session=self.active.session_data,
            )
            self._finalize_run(result)

    def record_command(self, command: str, *, result: Any | None = None, source: str = "agent") -> None:
        if self.active is None:
            return
        clean = command.strip()
        if not clean:
            return
        self.active.recent_commands.append(clean)
        self.active.session_data["last_command"] = clean
        self.active.session_data["last_command_source"] = source
        self.active.session_data["last_command_at"] = self._timestamp_iso_ms()
        payload: dict[str, Any] = {"command": clean, "source": source}
        if result is not None:
            payload["result"] = result
        self._append_event("sts2_command", clean, payload)
        self._write_summary()

    def record_note(self, kind: str, text: str, *, payload: dict[str, Any] | None = None) -> None:
        if self.active is None:
            return
        self._append_event(kind, text, payload or {})
        self._write_summary()

    def ensure_run_from_command(self, command: str, *, source: str = "agent", result: Any | None = None) -> bool:
        clean = command.strip()
        new_run_command = self._extract_new_run_command(clean)
        if new_run_command is None:
            return False
        if new_run_command.startswith("continue-game") and self.active is not None:
            return False
        self.pending_new_run = self._parse_pending_new_run(new_run_command, source=source)
        self.pending_run_command = {
            "command": new_run_command,
            "source": source,
            "result": result,
        }
        return True

    def record_agent_event(self, kind: str, text: str, *, data: dict[str, Any] | None = None) -> None:
        if self.active is None:
            return
        ledger_record = self._append_ledger(
            record_type="agent_event",
            text=text,
            kind=kind,
            data=data or {},
        )
        self._append_agent_event_view(ledger_record)
        self._write_session()

    def prepare_turn(self, iteration: int, *, mode: str, state: dict[str, Any] | None) -> None:
        summary = summarize_state(state)
        payload = {
            "iteration": iteration,
            "mode": mode,
            "state_summary": summary,
        }
        if self.active is None:
            self.pending_turn_start = payload
            return
        self._append_artifact(
            "turn_started",
            f"Turn {iteration:04d} started",
            payload,
        )

    def write_runtime_prompt(self, text: str, *, iteration: int, mode: str) -> Path | None:
        if self.active is None:
            return None
        path = self.active.data_dir / "runtime_prompt.md"
        path.write_text(text, encoding="utf-8")
        self._append_artifact(
            "runtime_prompt",
            f"Runtime prompt written for iteration {iteration:04d}",
            {
                "iteration": iteration,
                "mode": mode,
                "path": self._relative_run_path(path),
                "chars": len(text),
            },
        )
        return path

    def record_iteration_artifacts(self, iteration: int, *, raw_path: Path, text_path: Path) -> None:
        if self.active is None:
            return
        self._append_artifact(
            "iteration_artifacts",
            f"Iteration artifacts stored for {iteration:04d}",
            {
                "iteration": iteration,
                "raw_path": self._relative_run_path(raw_path),
                "text_path": self._relative_run_path(text_path),
            },
        )

    def finalize_if_active(self, result: str = "interrupted") -> None:
        if self.active is None:
            return
        self._finalize_run(result)

    def _start_run(self, summary: dict[str, Any], *, prime_summary: bool) -> None:
        run_id = self._build_run_id(summary)
        run_dir = self.runs_root / run_id
        memory_dir = run_dir / "memory"
        data_dir = run_dir / "data"
        memory_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        self.active = RunMemory(
            run_id=run_id,
            run_dir=run_dir,
            memory_dir=memory_dir,
            data_dir=data_dir,
            latest_summary=summary if prime_summary else None,
            session_data={
                "run_id": run_id,
                "status": "active",
                "character": summary.get("character"),
                "ascension": summary.get("ascension"),
                "seed": None,
                "started_at": self._timestamp_iso_ms(),
                "ended_at": None,
                "result": None,
                "latest_act": summary.get("act"),
                "latest_floor": summary.get("floor"),
                "latest_seq_id": 0,
                "latest_event_id": None,
                "latest_agent_seq_id": 0,
                "latest_decision": summary.get("decision"),
                "latest_state_type": summary.get("type"),
                "has_seen_non_menu_state": prime_summary and summary.get("decision") != "menu",
                "last_non_menu_decision": summary.get("decision") if summary.get("decision") not in {None, "menu"} else None,
                "last_state_source": None,
                "last_command": None,
                "last_command_source": None,
                "last_command_at": None,
                "route_history": [],
            },
        )
        self.last_run_dir = run_dir
        (data_dir / "iterations").mkdir(parents=True, exist_ok=True)
        (data_dir / "ledger.jsonl").write_text("", encoding="utf-8")
        (data_dir / "events.jsonl").write_text("", encoding="utf-8")
        (data_dir / "agent_events.jsonl").write_text("", encoding="utf-8")
        (data_dir / "runtime_prompt.md").write_text("", encoding="utf-8")
        self._update_latest_link(run_dir)
        self._write_session()
        self._write_state_snapshot(None, None, summary)
        self._write_summary()

    def _update_latest_link(self, run_dir: Path) -> None:
        try:
            if self.latest_link.is_symlink() or self.latest_link.exists():
                self.latest_link.unlink()
            self.latest_link.symlink_to(run_dir.relative_to(self.root))
        except OSError:
            pass

    def _build_run_id(self, summary: dict[str, Any]) -> str:
        ts = time.strftime("%Y%m%d-%H%M%S")
        character = str(summary.get("character") or "unknown").strip().lower().replace(" ", "-")
        asc = summary.get("ascension")
        asc_text = f"a{asc}" if asc is not None else "a?"
        suffix = secrets.token_hex(3)
        return f"{ts}-{character}-{asc_text}-{suffix}"

    def _append_event(self, event_type: str, text: str, payload: dict[str, Any]) -> None:
        if self.active is None:
            return
        ledger_record = self._append_ledger(
            record_type="event",
            text=text,
            event_type=event_type,
            payload=payload,
        )
        self._append_event_view(ledger_record)
        self._write_session()

    def _append_artifact(self, artifact_type: str, text: str, payload: dict[str, Any]) -> None:
        if self.active is None:
            return
        self._append_ledger(
            record_type="artifact",
            text=text,
            artifact_type=artifact_type,
            payload=payload,
        )
        self._write_session()

    def _flush_pending_run_command(self) -> None:
        if self.active is None or self.pending_run_command is None:
            return
        pending = self.pending_run_command
        self.pending_run_command = None
        self.record_command(
            str(pending.get("command") or "").strip(),
            result=pending.get("result"),
            source=str(pending.get("source") or "agent"),
        )

    def _flush_pending_turn_start(self, fallback_summary: dict[str, Any]) -> None:
        if self.active is None or self.pending_turn_start is None:
            return
        pending = dict(self.pending_turn_start)
        self.pending_turn_start = None
        if not isinstance(pending.get("state_summary"), dict):
            pending["state_summary"] = dict(fallback_summary)
        iteration = pending.get("iteration")
        label = f"Turn {int(iteration):04d} started" if isinstance(iteration, int) else "Turn started"
        self._append_artifact("turn_started", label, pending)

    def _append_ledger(
        self,
        *,
        record_type: str,
        text: str,
        payload: dict[str, Any] | None = None,
        event_type: str | None = None,
        kind: str | None = None,
        data: dict[str, Any] | None = None,
        artifact_type: str | None = None,
    ) -> dict[str, Any]:
        if self.active is None:
            raise RuntimeError("No active run")
        self.active.seq_counter += 1
        ts_ms = self._timestamp_ms()
        ts = self._timestamp_iso_ms(ts_ms)
        summary = self.active.latest_summary or {}
        record: dict[str, Any] = {
            "seq_id": self.active.seq_counter,
            "ts": ts,
            "ts_ms": ts_ms,
            "run_id": self.active.run_id,
            "record_type": record_type,
            "act": summary.get("act"),
            "floor": summary.get("floor"),
            "decision": summary.get("decision"),
            "text": text,
        }
        if record_type == "event":
            record["event_type"] = event_type
            record["event_id"] = f"evt_{record['seq_id']:010d}"
            record["payload"] = payload or {}
            self.active.session_data["latest_event_id"] = record["event_id"]
        elif record_type == "agent_event":
            record["kind"] = kind
            record["data"] = data or {}
            self.active.session_data["latest_agent_seq_id"] = record["seq_id"]
        elif record_type == "artifact":
            record["artifact_type"] = artifact_type
            record["payload"] = payload or {}
        self.active.session_data["latest_seq_id"] = record["seq_id"]
        self.active.session_data["last_updated_at"] = ts
        with (self.active.data_dir / "ledger.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def _append_event_view(self, ledger_record: dict[str, Any]) -> None:
        if self.active is None:
            return
        record = {
            "event_id": ledger_record["event_id"],
            "seq_id": ledger_record["seq_id"],
            "ts": ledger_record["ts"],
            "ts_ms": ledger_record["ts_ms"],
            "run_id": ledger_record["run_id"],
            "event_type": ledger_record["event_type"],
            "act": ledger_record.get("act"),
            "floor": ledger_record.get("floor"),
            "decision": ledger_record.get("decision"),
            "text": ledger_record["text"],
            "payload": ledger_record.get("payload", {}),
        }
        with (self.active.data_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _append_agent_event_view(self, ledger_record: dict[str, Any]) -> None:
        if self.active is None:
            return
        record = {
            "seq_id": ledger_record["seq_id"],
            "ts": ledger_record["ts"],
            "ts_ms": ledger_record["ts_ms"],
            "run_id": ledger_record["run_id"],
            "kind": ledger_record["kind"],
            "act": ledger_record.get("act"),
            "floor": ledger_record.get("floor"),
            "decision": ledger_record.get("decision"),
            "text": ledger_record["text"],
            "data": ledger_record.get("data", {}),
        }
        with (self.active.data_dir / "agent_events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _write_state_snapshot(
        self,
        state: dict[str, Any] | None,
        raw_state: dict[str, Any] | None,
        summary: dict[str, Any],
    ) -> None:
        if self.active is None:
            return
        payload = {
            "captured_at": self._timestamp_iso_ms(),
            "normalized_state": state,
            "raw_bridge_state": raw_state,
            "derived_summary": summary,
        }
        (self.active.data_dir / "state_snapshot.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_session(self) -> None:
        if self.active is None:
            return
        (self.active.data_dir / "session.json").write_text(
            json.dumps(self.active.session_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_summary(self) -> None:
        if self.active is None:
            return
        summary = self.active.latest_summary or {}
        state = self.active.latest_state or {}
        session = self.active.session_data
        character = summary.get("character") if summary.get("character") is not None else session.get("character")
        ascension = summary.get("ascension") if summary.get("ascension") is not None else session.get("ascension")
        act = summary.get("act") if summary.get("act") is not None else session.get("latest_act")
        floor = summary.get("floor") if summary.get("floor") is not None else session.get("latest_floor")
        hp = summary.get("hp") if summary.get("hp") is not None else session.get("last_hp")
        max_hp = summary.get("max_hp") if summary.get("max_hp") is not None else session.get("last_max_hp")
        gold = summary.get("gold") if summary.get("gold") is not None else session.get("last_gold")
        lines = [
            "# Run Summary",
            "",
            f"- Run ID: {self.active.run_id}",
            f"- Status: {session.get('status') if session.get('status') is not None else '-'}",
            f"- Result: {session.get('result') if session.get('result') is not None else '-'}",
            f"- Character: {character if character is not None else '-'}",
            f"- Ascension: {ascension if ascension is not None else '-'}",
            f"- Act: {act if act is not None else '-'}",
            f"- Floor: {floor if floor is not None else '-'}",
            f"- Decision: {summary.get('decision', '-')}",
            f"- HP: {hp if hp is not None else '-'} / {max_hp if max_hp is not None else '-'}",
            f"- Gold: {gold if gold is not None else '-'}",
            "",
            "## Current Situation",
            f"- Type: {summary.get('type', '-')}",
            f"- Decision: {summary.get('decision', '-')}",
            "",
            "## Current Decision Details",
        ]

        lines.extend(self._build_decision_section(state))

        lines.extend(["", "## Route So Far"])
        lines.extend(self._build_route_section(state, session))

        lines.extend(["", "## Recent Commands"])
        if self.active.recent_commands:
            lines.extend([f"- {cmd}" for cmd in list(self.active.recent_commands)[-10:]])
        else:
            lines.append("- (none)")

        lines.extend(["", "## Recent State Changes"])
        if self.active.recent_state_changes:
            lines.extend([f"- {item}" for item in list(self.active.recent_state_changes)[:12]])
        else:
            lines.append("- (none)")

        lines.extend(["", "## Agent Usage Note"])
        lines.append("- It is a compressed short-term memory, not the source of truth.")
        lines.append("- Current `sts2 state` still overrides anything recorded here.")

        (self.active.memory_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _build_route_section(self, state: dict[str, Any], session: dict[str, Any]) -> list[str]:
        visited = state.get("visited")
        if not isinstance(visited, list) or not visited:
            visited = session.get("route_history")
        if not isinstance(visited, list) or not visited:
            return ["- (no route history yet)"]
        lines: list[str] = []
        for entry in visited[-10:]:
            if not isinstance(entry, dict):
                continue
            lines.append(f"- ({entry.get('col', '-')}, {entry.get('row', '-')}) {entry.get('type', '-')}")
        return lines or ["- (no route history yet)"]

    def _build_decision_section(self, state: dict[str, Any]) -> list[str]:
        decision = state.get("decision")
        lines: list[str] = []

        if decision == "combat_play":
            energy = state.get("energy")
            max_energy = state.get("max_energy")
            enemies = state.get("enemies") if isinstance(state.get("enemies"), list) else []
            hand = state.get("hand") if isinstance(state.get("hand"), list) else []
            lines.append(f"- Energy: {energy} / {max_energy}")
            if enemies:
                lines.append("- Enemies:")
                for enemy in enemies[:3]:
                    if not isinstance(enemy, dict):
                        continue
                    intent = ""
                    intents = enemy.get("intents")
                    if isinstance(intents, list) and intents:
                        first = intents[0]
                        if isinstance(first, dict):
                            intent = f" | intent: {first.get('type', '-')}" + (
                                f" {first.get('label', '')}" if first.get("label") is not None else ""
                            )
                    lines.append(
                        f"  - {enemy.get('name', '-')} {enemy.get('hp', '-')} / {enemy.get('max_hp', '-')}{intent}"
                    )
            if hand:
                lines.append("- Hand:")
                for card in hand[:10]:
                    if not isinstance(card, dict):
                        continue
                    lines.append(
                        f"  - [{card.get('index', '-')}] {card.get('name', '-')} cost={card.get('cost', '-')} can_play={card.get('can_play', False)}"
                    )
            return lines or ["- (combat details unavailable)"]

        if decision == "map_select":
            choices = state.get("choices") if isinstance(state.get("choices"), list) else []
            current = state.get("current_position") if isinstance(state.get("current_position"), dict) else {}
            lines.append(
                f"- Current Position: ({current.get('col', '-')}, {current.get('row', '-')}) {current.get('type', '-')}"
            )
            if choices:
                lines.append("- Next Choices:")
                for choice in choices[:8]:
                    if not isinstance(choice, dict):
                        continue
                    lines.append(
                        f"  - [{choice.get('index', '-')}] ({choice.get('col', '-')}, {choice.get('row', '-')}) {choice.get('type', '-')}"
                    )
            return lines or ["- (map details unavailable)"]

        if decision == "hand_select":
            lines.append(f"- Prompt: {state.get('prompt', '-')}")
            lines.append(f"- Mode: {state.get('mode', '-')}")
            lines.append(f"- Can Confirm: {state.get('can_confirm', False)}")
            cards = state.get("cards") if isinstance(state.get("cards"), list) else []
            if cards:
                lines.append("- Selectable Cards:")
                for card in cards[:10]:
                    if not isinstance(card, dict):
                        continue
                    lines.append(f"  - [{card.get('index', '-')}] {card.get('name', '-')}")
            selected = state.get("selected_cards") if isinstance(state.get("selected_cards"), list) else []
            if selected:
                lines.append("- Selected Cards:")
                for card in selected[:10]:
                    if not isinstance(card, dict):
                        continue
                    lines.append(f"  - [{card.get('index', '-')}] {card.get('name', '-')}")
            return lines or ["- (hand-select details unavailable)"]

        if decision == "event_choice":
            lines.append(f"- Event: {state.get('event_name', '-')}")
            options = state.get("options") if isinstance(state.get("options"), list) else []
            if options:
                lines.append("- Options:")
                for option in options[:8]:
                    if not isinstance(option, dict):
                        continue
                    lines.append(
                        f"  - [{option.get('index', '-')}] {option.get('title', '-')}"
                    )
            return lines or ["- (event details unavailable)"]

        if decision == "card_reward":
            cards = state.get("cards") if isinstance(state.get("cards"), list) else []
            if cards:
                lines.append("- Card Rewards:")
                for card in cards[:5]:
                    if not isinstance(card, dict):
                        continue
                    lines.append(f"  - [{card.get('index', '-')}] {card.get('name', '-')}")
            return lines or ["- (card reward details unavailable)"]

        if decision == "combat_rewards":
            items = state.get("items") if isinstance(state.get("items"), list) else []
            if items:
                lines.append("- Rewards:")
                for item in items[:8]:
                    if not isinstance(item, dict):
                        continue
                    lines.append(
                        f"  - [{item.get('index', '-')}] {item.get('type', '-')}"
                    )
            return lines or ["- (combat reward details unavailable)"]

        if decision == "rest_site":
            options = state.get("options") if isinstance(state.get("options"), list) else []
            if options:
                lines.append("- Rest Options:")
                for option in options[:8]:
                    if not isinstance(option, dict):
                        continue
                    lines.append(
                        f"  - [{option.get('index', '-')}] {option.get('id', option.get('title', '-'))}"
                    )
            return lines or ["- (rest-site details unavailable)"]

        if decision == "shop":
            items = state.get("items") if isinstance(state.get("items"), list) else []
            lines.append(f"- Items visible: {len(items)}")
            card_removal = state.get("card_removal")
            if isinstance(card_removal, dict):
                lines.append(f"- Card Removal: index={card_removal.get('index', '-')} cost={card_removal.get('price', '-')}")
            return lines

        if decision == "card_select":
            lines.append(f"- Screen Type: {state.get('screen_type', '-')}")
            lines.append(f"- Prompt: {state.get('prompt', '-')}")
            lines.append(f"- Preview Showing: {state.get('preview_showing', False)}")
            lines.append(f"- Can Skip: {state.get('can_skip', False)}")
            lines.append(f"- Can Confirm: {state.get('can_confirm', False)}")
            lines.append(f"- Can Cancel: {state.get('can_cancel', False)}")
            cards = state.get("cards") if isinstance(state.get("cards"), list) else []
            if cards:
                lines.append("- Cards:")
                for card in cards[:10]:
                    if not isinstance(card, dict):
                        continue
                    lines.append(f"  - [{card.get('index', '-')}] {card.get('name', '-')}")
            return lines or ["- (card-select details unavailable)"]

        if decision == "relic_select":
            lines.append(f"- Prompt: {state.get('prompt', '-')}")
            lines.append(f"- Can Skip: {state.get('can_skip', False)}")
            relics = state.get("relics") if isinstance(state.get("relics"), list) else []
            if relics:
                lines.append("- Relics:")
                for relic in relics[:8]:
                    if not isinstance(relic, dict):
                        continue
                    lines.append(f"  - [{relic.get('index', '-')}] {relic.get('name', '-')}")
            return lines or ["- (relic-select details unavailable)"]

        if decision == "treasure":
            lines.append(f"- Can Proceed: {state.get('can_proceed', False)}")
            relics = state.get("relics") if isinstance(state.get("relics"), list) else []
            if relics:
                lines.append("- Treasure Relics:")
                for relic in relics[:8]:
                    if not isinstance(relic, dict):
                        continue
                    lines.append(f"  - [{relic.get('index', '-')}] {relic.get('name', '-')}")
            return lines or ["- (treasure details unavailable)"]

        if decision == "overlay":
            overlay = state.get("overlay") if isinstance(state.get("overlay"), dict) else {}
            lines.append(f"- Overlay Screen: {overlay.get('screen_type', state.get('screen_type', '-'))}")
            return lines

        if decision == "game_over":
            lines.append("- Game over screen is active.")
            lines.append(f"- Can Return To Main Menu: {state.get('can_return_to_main_menu', False)}")
            lines.append(f"- Can Continue: {state.get('can_continue', False)}")
            options = state.get("options") if isinstance(state.get("options"), list) else []
            if options:
                lines.append("- Options:")
                for option in options[:8]:
                    if not isinstance(option, dict):
                        continue
                    lines.append(
                        f"  - {option.get('id', '-')} enabled={option.get('is_enabled', False)}"
                    )
            return lines

        if decision == "menu":
            screen = state.get("screen") or (state.get("menu") or {}).get("screen")
            lines.append(f"- Menu Screen: {screen or '-'}")
            lines.append(f"- Can Continue Game: {state.get('can_continue_game', False)}")
            lines.append(f"- Can Start New Game: {state.get('can_start_new_game', False)}")
            return lines

        return ["- (no decision-specific summary available)"]

    def _update_session_from_summary(
        self,
        summary: dict[str, Any],
        *,
        state: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> None:
        if self.active is None:
            return
        session = self.active.session_data
        session["latest_decision"] = summary.get("decision")
        session["latest_state_type"] = summary.get("type")
        if source is not None:
            session["last_state_source"] = source
        if summary.get("decision") not in {None, "menu"}:
            session["has_seen_non_menu_state"] = True
            session["last_non_menu_decision"] = summary.get("decision")
        if summary.get("character") is not None:
            session["character"] = summary.get("character")
        if summary.get("ascension") is not None:
            session["ascension"] = summary.get("ascension")
        if summary.get("act") is not None:
            session["latest_act"] = summary.get("act")
        if summary.get("floor") is not None:
            session["latest_floor"] = summary.get("floor")
        if summary.get("hp") is not None:
            session["last_hp"] = summary.get("hp")
        if summary.get("max_hp") is not None:
            session["last_max_hp"] = summary.get("max_hp")
        if summary.get("gold") is not None:
            session["last_gold"] = summary.get("gold")
        if state is not None:
            visited = state.get("visited")
            if isinstance(visited, list) and visited:
                session["route_history"] = [
                    {
                        "col": entry.get("col"),
                        "row": entry.get("row"),
                        "type": entry.get("type"),
                    }
                    for entry in visited[-20:]
                    if isinstance(entry, dict)
                ]
        self._write_session()

    def _finalize_run(self, result: str) -> None:
        if self.active is None:
            return
        run_dir = self.active.run_dir
        self.active.session_data["status"] = result if result not in {"", "unknown"} else "finished"
        self.active.session_data["ended_at"] = self._timestamp_iso_ms()
        self.active.session_data["result"] = result
        self._append_event("run_ended", f"Run ended: {result}", {"result": result})
        self._write_summary()
        self._write_session()
        try:
            self.v2.materialize_run(run_dir)
            self.active.session_data["v2_materialized_at"] = self._timestamp_iso_ms()
            self.active.session_data["v2_materialize_error"] = None
        except Exception as exc:  # noqa: BLE001
            self.active.session_data["v2_materialize_error"] = str(exc)
        self._write_session()
        self.last_run_dir = run_dir
        self.active = None

    def _menu_keeps_run_active(self, state: dict[str, Any] | None) -> bool:
        if self.active is None or not isinstance(state, dict):
            return False
        if state.get("decision") != "menu":
            return False
        return bool(state.get("can_continue_game")) and bool(self.active.session_data.get("has_seen_non_menu_state"))

    def _should_finalize_on_menu_state(
        self,
        *,
        previous_summary: dict[str, Any],
        previous_state: dict[str, Any] | None,
        current_summary: dict[str, Any],
        current_state: dict[str, Any] | None,
    ) -> bool:
        if current_summary.get("decision") != "menu":
            return False

        current_keeps_run = self._menu_keeps_run_active(current_state)
        if previous_summary.get("decision") != "menu":
            return not current_keeps_run

        previous_keeps_run = self._menu_keeps_run_active(previous_state)
        return previous_keeps_run and not current_keeps_run

    def _diff_summary(
        self,
        previous: dict[str, Any],
        current: dict[str, Any],
    ) -> list[tuple[str, str, dict[str, Any]]]:
        changes: list[tuple[str, str, dict[str, Any]]] = []

        if previous.get("decision") != current.get("decision"):
            changes.append(
                (
                    "state_transition",
                    f"{previous.get('decision') or '-'} -> {current.get('decision') or '-'}",
                    {"from": previous.get("decision"), "to": current.get("decision")},
                )
            )

        if previous.get("act") != current.get("act"):
            if current.get("act") is not None:
                changes.append(
                    (
                        "act_change",
                        f"{previous.get('act') or '-'} -> {current.get('act') or '-'}",
                        {"from": previous.get("act"), "to": current.get("act")},
                    )
                )

        if previous.get("hp") != current.get("hp") or previous.get("max_hp") != current.get("max_hp"):
            if current.get("hp") is not None or current.get("max_hp") is not None:
                old_hp = previous.get("hp")
                new_hp = current.get("hp")
                old_max = previous.get("max_hp")
                new_max = current.get("max_hp")
                delta_text = ""
                if isinstance(old_hp, (int, float)) and isinstance(new_hp, (int, float)):
                    delta = int(new_hp - old_hp)
                    if delta != 0:
                        delta_text = f" ({delta:+d})"
                changes.append(
                    (
                        "hp_change",
                        f"{old_hp} / {old_max} -> {new_hp} / {new_max}{delta_text}",
                        {"from": [old_hp, old_max], "to": [new_hp, new_max]},
                    )
                )

        if previous.get("floor") != current.get("floor"):
            if current.get("floor") is not None:
                changes.append(
                    (
                        "floor_change",
                        f"{previous.get('floor') or '-'} -> {current.get('floor') or '-'}",
                        {"from": previous.get("floor"), "to": current.get("floor")},
                    )
                )

        if previous.get("gold") != current.get("gold"):
            if current.get("gold") is not None:
                old_gold = previous.get("gold")
                new_gold = current.get("gold")
                delta_text = ""
                if isinstance(old_gold, (int, float)) and isinstance(new_gold, (int, float)):
                    delta = int(new_gold - old_gold)
                    if delta != 0:
                        delta_text = f" ({delta:+d})"
                changes.append(
                    (
                        "gold_change",
                        f"{old_gold} -> {new_gold}{delta_text}",
                        {"from": old_gold, "to": new_gold},
                    )
                )

        return changes

    def _infer_result(
        self,
        summary: dict[str, Any],
        *,
        current_state: dict[str, Any] | None = None,
        previous_summary: dict[str, Any] | None = None,
        previous_state: dict[str, Any] | None = None,
        session: dict[str, Any] | None = None,
    ) -> str:
        session = session or {}
        previous_summary = previous_summary or {}
        decision = summary.get("decision")
        state_for_hp = current_state

        if decision == "menu" and previous_summary.get("decision") == "game_over":
            decision = "game_over"
            state_for_hp = previous_state

        last_command = str(session.get("last_command") or "").strip()
        if (
            decision == "menu"
            and last_command.startswith("abandon-game")
            and isinstance(current_state, dict)
            and not bool(current_state.get("can_continue_game"))
        ):
            return "abandoned"

        if decision in {None, "menu"}:
            decision = session.get("last_non_menu_decision")
        hp = previous_summary.get("hp") if previous_summary.get("decision") == "game_over" else summary.get("hp")
        if hp is None and isinstance(state_for_hp, dict):
            player = state_for_hp.get("player")
            if isinstance(player, dict):
                hp = player.get("hp")
        if hp is None:
            hp = session.get("last_hp")

        if decision == "game_over":
            if isinstance(hp, (int, float)) and hp > 0:
                return "won"
            return "lost"
        return "unknown"

    def _extract_new_run_command(self, command: str) -> str | None:
        clean = command.strip()
        if clean.startswith("start-game") or clean.startswith("continue-game"):
            return clean
        for segment in extract_sts2_segments(command):
            subcommand = segment.removeprefix("sts2 ").strip()
            if subcommand.startswith("start-game") or subcommand.startswith("continue-game"):
                return subcommand
        return None

    def _parse_pending_new_run(self, command: str, *, source: str) -> dict[str, Any]:
        character = None
        ascension = None
        if command.startswith("start-game"):
            character = "unknown"
            parts = command.split()
            for idx, part in enumerate(parts):
                if part == "--character" and idx + 1 < len(parts):
                    character = parts[idx + 1]
                if part == "--ascension" and idx + 1 < len(parts):
                    try:
                        ascension = int(parts[idx + 1])
                    except ValueError:
                        ascension = None
        return {
            "command": command,
            "source": source,
            "character": character,
            "ascension": ascension,
        }

    def _merge_summary_with_pending(self, summary: dict[str, Any]) -> dict[str, Any]:
        if self.pending_new_run is None:
            return summary
        merged = dict(summary)
        if merged.get("character") in {None, "", "unknown"} and self.pending_new_run.get("character") is not None:
            merged["character"] = self.pending_new_run["character"]
        if merged.get("ascension") is None and self.pending_new_run.get("ascension") is not None:
            merged["ascension"] = self.pending_new_run["ascension"]
        return merged

    def _should_split_on_new_state(self, summary: dict[str, Any]) -> bool:
        if self.active is None or self.pending_new_run is None:
            return False
        if summary.get("decision") == "menu":
            return False

        previous = self.active.latest_summary or {}
        if previous.get("decision") == "game_over":
            return True
        if previous.get("decision") == "menu" and self.active.session_data.get("has_seen_non_menu_state"):
            return True

        prev_floor = previous.get("floor")
        curr_floor = summary.get("floor")
        if isinstance(prev_floor, (int, float)) and isinstance(curr_floor, (int, float)) and curr_floor < prev_floor:
            return True

        prev_act = previous.get("act")
        curr_act = summary.get("act")
        if isinstance(prev_act, (int, float)) and isinstance(curr_act, (int, float)) and curr_act < prev_act:
            return True

        return False

    def _relative_run_path(self, path: Path) -> str:
        if self.active is None:
            return str(path)
        try:
            return str(path.relative_to(self.active.run_dir))
        except ValueError:
            return str(path)

    def _timestamp_ms(self) -> int:
        return time.time_ns() // 1_000_000

    def _timestamp_iso_ms(self, ts_ms: int | None = None) -> str:
        if ts_ms is None:
            ts_ms = self._timestamp_ms()
        return (
            datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
