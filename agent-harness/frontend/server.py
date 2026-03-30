#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
LOG_ROOT = ROOT / "logs" / "frontend-agent"

PI_RUNTIME_ROOT = ROOT / "agent-harness" / "pi-agent" / "runtime"
PI_BIN = PI_RUNTIME_ROOT / "node_modules" / ".bin" / "pi"
PI_SETUP_SCRIPT = ROOT / "agent-harness" / "pi-agent" / "setup_pi_agent.sh"
PI_PACKAGE_NAME = "@mariozechner/pi-coding-agent"
PI_PACKAGE_VERSION = "0.62.0"
BASE_PROMPT_PATH = ROOT / "agent-harness" / "pi-agent" / "base-prompt.md"

STS2_BIN = ROOT / "sts2"
SKILL_PATH = ROOT / "agent-harness" / "skills"
APPEND_PROMPT = ROOT / "agent-harness" / "pi-agent" / "append-system-prompt.md"
ENV_FILE = ROOT / ".env"
MEMORY_ROOT = ROOT / "memory"
MEMORY_SKILL_NAME = "sts2-v2-memory"
MEMORY_V3_SKILL_NAME = "sts2-v3-workspace"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_v1 import MemoryV1Store, summarize_state  # noqa: E402
from memory_v3 import MemoryV3Workspace  # noqa: E402
from sts2_commands import extract_sts2_segments, has_sts2_subcommand, normalize_sts2_command  # noqa: E402
from sts2cli.http_client import ApiError, Sts2RawClient  # noqa: E402
from sts2cli.state_adapter import normalize_state  # noqa: E402


def load_env_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = raw_line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        result[key] = value
    return result


def derive_api_key_env(provider: str) -> str:
    env_map = {
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "cerebras": "CEREBRAS_API_KEY",
        "xai": "XAI_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "zai": "ZAI_API_KEY",
        "huggingface": "HF_TOKEN",
        "kimi-coding": "KIMI_API_KEY",
        "minimax": "MINIMAX_API_KEY",
        "minimax-cn": "MINIMAX_CN_API_KEY",
        "vercel-ai-gateway": "AI_GATEWAY_API_KEY",
    }
    return env_map.get(provider, "")


def short_json(value: Any, limit: int = 240) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except TypeError:
        text = repr(value)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "stdout", "stderr", "message", "content"):
            child = value.get(key)
            extracted = extract_text(child)
            if extracted:
                return extracted
    if isinstance(value, list):
        parts = [extract_text(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    return ""


def extract_bash_command(data: dict[str, Any] | None) -> str | None:
    if not isinstance(data, dict):
        return None
    if str(data.get("toolName") or "") != "bash":
        return None
    args = data.get("args")
    if isinstance(args, dict):
        command = args.get("command")
        if isinstance(command, str) and command.strip():
            return command.strip()
    return None


def extract_json_dicts(text: str) -> list[dict[str, Any]]:
    candidate = text.strip()
    if not candidate:
        return []
    decoder = json.JSONDecoder()
    items: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(candidate):
        start = candidate.find("{", cursor)
        if start == -1:
            break
        try:
            data, end = decoder.raw_decode(candidate[start:])
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        if isinstance(data, dict):
            items.append(data)
        cursor = start + max(end, 1)
    return items


def parse_sts2_state_output(text: str) -> dict[str, Any] | None:
    last_state: dict[str, Any] | None = None
    for data in extract_json_dicts(text):
        if "decision" in data or ("type" in data and "context" in data) or "state_type" in data:
            last_state = data
    return last_state


def bash_command_succeeded(text: str) -> bool:
    for data in extract_json_dicts(text):
        if str(data.get("status") or "").strip().lower() == "ok":
            return True
    return False


def resolve_pi_bin(env: dict[str, str]) -> str:
    candidate = env.get("PI_BIN", str(PI_BIN))
    if "/" in candidate:
        return candidate
    resolved = shutil.which(candidate, path=env.get("PATH"))
    return resolved or candidate


def resolve_sts2_bin(env: dict[str, str]) -> str:
    candidate = env.get("STS2_BIN", "")
    if candidate:
        candidate_path = Path(candidate).expanduser()
        if candidate_path.is_file() and os.access(candidate_path, os.X_OK):
            return str(candidate_path)
        resolved = shutil.which(candidate, path=env.get("PATH"))
        if resolved:
            return resolved

    if STS2_BIN.is_file() and os.access(STS2_BIN, os.X_OK):
        return str(STS2_BIN)

    resolved = shutil.which("sts2", path=env.get("PATH"))
    return resolved or str(STS2_BIN)


def _strip_quotes(text: str) -> str:
    value = text.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def discover_skills(skill_root: Path) -> list[dict[str, str]]:
    if not skill_root.exists():
        return []
    skill_files = []
    if skill_root.is_file() and skill_root.name == "SKILL.md":
        skill_files = [skill_root]
    elif skill_root.is_dir():
        skill_files = sorted(skill_root.rglob("SKILL.md"))
    skills: list[dict[str, str]] = []
    for skill_file in skill_files:
        name = skill_file.parent.name
        description = ""
        try:
            lines = skill_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        if lines and lines[0].strip() == "---":
            for raw_line in lines[1:]:
                line = raw_line.strip()
                if line == "---":
                    break
                if line.startswith("name:"):
                    name = _strip_quotes(line.split(":", 1)[1])
                elif line.startswith("description:"):
                    description = _strip_quotes(line.split(":", 1)[1])
        skills.append(
            {
                "name": name,
                "description": description,
                "path": str(skill_file),
                "base_dir": str(skill_file.parent),
            }
        )
    return skills


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
    except OSError:
        return False


def extract_tool_args(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    args = data.get("args")
    return args if isinstance(args, dict) else None


def extract_read_path(data: dict[str, Any] | None) -> Path | None:
    if not isinstance(data, dict) or str(data.get("toolName") or "") != "read":
        return None
    args = extract_tool_args(data)
    if not isinstance(args, dict):
        return None
    candidate = args.get("path") or args.get("file_path")
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def summarize_preview(text: str, limit: int = 800) -> str:
    compact = text.strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def classify_memory_target(path: str | None = None, command: str | None = None) -> str:
    candidate = (path or command or "").replace("\\", "/").lower()
    if not candidate:
        return "memory"
    if "/globao_memory/" in candidate:
        return "v3"
    if "index.sqlite" in candidate or "sqlite3 " in candidate:
        return "sqlite"
    if "/turns/" in candidate:
        return "turns"
    if "/rewards/" in candidate:
        return "rewards"
    if "/battles/" in candidate:
        return "battles"
    if "/derived/" in candidate:
        return "derived"
    if "/memory/summary.md" in candidate or candidate.endswith("/summary.md"):
        return "summary"
    if "/data/" in candidate or any(token in candidate for token in ("events.jsonl", "ledger.jsonl", "session.json", "state_snapshot.json")):
        return "data"
    return "memory"


def parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return int(text)


def parse_bool_env(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class ParsedPiEvent:
    kind: str
    text: str
    data: dict[str, Any]


class PiEventParser:
    def __init__(self) -> None:
        self._assistant_text_started = False
        self._thinking_started = False

    def parse_line(self, raw_line: str) -> list[ParsedPiEvent]:
        line = raw_line.rstrip("\n")
        if not line:
            return []

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return [ParsedPiEvent("log", line, {})]

        event_type = event.get("type")
        if event_type == "message_update":
            return self._handle_message_update(event)
        if event_type == "tool_execution_start":
            tool_name = str(event.get("toolName") or "tool")
            args = short_json(event.get("args"))
            return [ParsedPiEvent("tool_start", f"{tool_name} {args}".rstrip(), event)]
        if event_type == "tool_execution_update":
            partial = extract_text(event.get("partialResult"))
            return [ParsedPiEvent("tool_update", partial, event)] if partial else []
        if event_type == "tool_execution_end":
            tool_name = str(event.get("toolName") or "tool")
            result_text = extract_text(event.get("result")) or short_json(event.get("result"))
            kind = "tool_error" if event.get("isError") else "tool_end"
            label = f"{tool_name} {result_text}".rstrip()
            return [ParsedPiEvent(kind, label, event)]
        if event_type == "message_end":
            message = event.get("message")
            if isinstance(message, dict) and message.get("role") == "assistant":
                self._assistant_text_started = False
                self._thinking_started = False
                text = "".join(
                    block.get("text", "")
                    for block in message.get("content", [])
                    if isinstance(block, dict) and block.get("type") == "text"
                )
                if text:
                    return [ParsedPiEvent("assistant_done", text, event)]
            return []
        if event_type in {"agent_start", "agent_end", "turn_start", "turn_end", "session", "message_start"}:
            return []
        return [ParsedPiEvent("raw_event", line, event)]

    def _handle_message_update(self, event: dict[str, Any]) -> list[ParsedPiEvent]:
        assistant_event = event.get("assistantMessageEvent")
        if not isinstance(assistant_event, dict):
            return []
        update_type = assistant_event.get("type")
        if update_type == "thinking_delta":
            delta = assistant_event.get("delta")
            if isinstance(delta, str) and delta:
                self._thinking_started = True
                return [ParsedPiEvent("thinking_delta", delta, assistant_event)]
            return []
        if update_type == "thinking_end":
            self._thinking_started = False
            return []
        if update_type == "text_delta":
            delta = assistant_event.get("delta")
            if isinstance(delta, str) and delta:
                self._assistant_text_started = True
                return [ParsedPiEvent("assistant_text_delta", delta, assistant_event)]
            return []
        if update_type == "text_end":
            self._assistant_text_started = False
            return []
        return []


class EventBuffer:
    def __init__(self, max_events: int = 4000) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._next_id = 1

    def append(self, kind: str, text: str = "", data: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            event = {
                "id": self._next_id,
                "ts": time.time(),
                "kind": kind,
                "text": text,
                "data": data or {},
            }
            self._next_id += 1
            self._events.append(event)
            return event

    def list_after(self, after: int) -> list[dict[str, Any]]:
        with self._lock:
            return [event for event in self._events if event["id"] > after]

    def latest_id(self) -> int:
        with self._lock:
            return self._events[-1]["id"] if self._events else 0


class AgentController:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events = EventBuffer()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None
        self._stop_requested = False
        self._pause_requested = False
        self._resume_mode: str | None = None
        self._mode: str = "idle"
        self._iteration = 0
        self._session_dir: Path | None = None
        self._live_thinking = ""
        self._live_output = ""
        self._last_warning = ""
        self._last_error = ""
        self._last_exit_code: int | None = None
        self._last_state: dict[str, Any] | None = None
        self._last_raw_state: dict[str, Any] | None = None
        self._active_tools: list[dict[str, Any]] = []
        self._tool_commands: dict[str, str] = {}
        self._recent_commands: deque[str] = deque(maxlen=100)
        self._current_iteration: int | None = None
        self._tracked_state_summary: dict[str, Any] | None = None
        self._last_reported_sts2_bin: str | None = None
        self._loaded_skills = discover_skills(SKILL_PATH)
        self._recent_skill_invocations: deque[dict[str, Any]] = deque(maxlen=30)
        self._recent_memory_fetches: deque[dict[str, Any]] = deque(maxlen=20)
        self._skills_used_this_iteration: set[str] = set()
        self._memory = MemoryV1Store(ROOT / "memory")
        self._memory_v3 = MemoryV3Workspace(ROOT / "memory")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            memory_info = self._memory.get_active_run_info() or self._memory.get_last_run_info()
            return {
                "status": self._mode,
                "iteration": self._iteration,
                "current_iteration": self._current_iteration,
                "session_dir": None if self._session_dir is None else str(self._session_dir),
                "process_running": self._process is not None and self._process.poll() is None,
                "pause_requested": self._pause_requested,
                "stop_requested": self._stop_requested,
                "resume_mode": self._resume_mode,
                "last_warning": self._last_warning,
                "last_error": self._last_error,
                "last_exit_code": self._last_exit_code,
                "live": {
                    "thinking": self._live_thinking[-12000:],
                    "output": self._live_output[-12000:],
                    "recent_commands": list(self._recent_commands),
                    "active_tools": list(self._active_tools),
                },
                "game": summarize_state(self._last_state),
                "latest_event_id": self._events.latest_id(),
                "memory": memory_info,
                "memory_summary": self._memory.get_visible_summary(),
                "memory_v3": self._memory_v3.status(),
                "skills": {
                    "root": str(SKILL_PATH),
                    "loaded": [
                        {
                            "name": skill["name"],
                            "description": skill["description"],
                            "path": skill["path"],
                        }
                        for skill in self._loaded_skills
                    ],
                    "recent_invocations": list(self._recent_skill_invocations),
                },
                "memory_fetches": {
                    "items": list(self._recent_memory_fetches),
                },
            }

    def list_events(self, after: int) -> list[dict[str, Any]]:
        return self._events.list_after(after)

    def fetch_state(self) -> dict[str, Any]:
        client = Sts2RawClient()
        raw = client.get_state(format="json")
        state = normalize_state(raw)
        with self._lock:
            self._last_raw_state = raw
            self._last_state = state
        return {"ok": True, "state": state, "summary": summarize_state(state)}

    def safe_fetch_state(self) -> tuple[bool, dict[str, Any] | None, str | None]:
        try:
            result = self.fetch_state()
            return True, result["state"], None
        except Exception as exc:  # noqa: BLE001
            return False, None, str(exc)

    def search_memory_runs(self, params: dict[str, str]) -> dict[str, Any]:
        limit = parse_optional_int(params.get("limit")) or 20
        limit = max(1, min(limit, 100))
        results = self._memory.v2.search_runs(
            character=(params.get("character") or "").strip() or None,
            result=(params.get("result") or "").strip() or None,
            boss=(params.get("boss") or "").strip() or None,
            death_enemy=(params.get("death_enemy") or "").strip() or None,
            card_name=(params.get("card_name") or "").strip() or None,
            relic_name=(params.get("relic_name") or "").strip() or None,
            floor_min=parse_optional_int(params.get("floor_min")),
            floor_max=parse_optional_int(params.get("floor_max")),
            limit=limit,
        )
        return {
            "ok": True,
            "filters": {
                "character": (params.get("character") or "").strip() or None,
                "result": (params.get("result") or "").strip() or None,
                "boss": (params.get("boss") or "").strip() or None,
                "death_enemy": (params.get("death_enemy") or "").strip() or None,
                "card_name": (params.get("card_name") or "").strip() or None,
                "relic_name": (params.get("relic_name") or "").strip() or None,
                "floor_min": parse_optional_int(params.get("floor_min")),
                "floor_max": parse_optional_int(params.get("floor_max")),
                "limit": limit,
            },
            "runs": results,
        }

    def get_memory_run_detail(self, run_id: str) -> dict[str, Any]:
        detail = self._memory.v2.get_run_detail(run_id.strip())
        if detail is None:
            raise ValueError(f"Run not found: {run_id}")
        return {"ok": True, "detail": detail}

    def get_memory_stats(self, params: dict[str, str]) -> dict[str, Any]:
        character = (params.get("character") or "").strip() or None
        return {"ok": True, "stats": self._memory.v2.get_stats(character=character)}

    def get_memory_v3_status(self) -> dict[str, Any]:
        return {"ok": True, "workspace": self._memory_v3.status()}

    def search_memory_v3(self, params: dict[str, str]) -> dict[str, Any]:
        query = (params.get("q") or "").strip() or None
        limit = parse_optional_int(params.get("limit")) or 50
        limit = max(1, min(limit, 200))
        return {"ok": True, "workspace": self._memory_v3.search(query=query, limit=limit)}

    def get_memory_v3_file(self, relative_path: str) -> dict[str, Any]:
        return {"ok": True, "file": self._memory_v3.read_file(relative_path)}

    def start(self, mode: str) -> dict[str, Any]:
        if mode not in {"single", "full_auto"}:
            raise ValueError(f"Unsupported mode: {mode}")
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("Agent is already running")

            self._loaded_skills = discover_skills(SKILL_PATH)
            self._stop_requested = False
            self._pause_requested = False
            self._resume_mode = mode if mode != "single" else "full_auto"
            self._mode = f"running_{mode}"
            self._live_thinking = ""
            self._live_output = ""
            self._last_error = ""
            self._last_exit_code = None
            self._active_tools.clear()
            self._tool_commands.clear()
            self._recent_commands.clear()
            self._tracked_state_summary = None
            self._skills_used_this_iteration = set()
            self._session_dir = self._create_session_dir()
            self._events.append("runner", f"Start mode: {mode}")
            self._thread = threading.Thread(target=self._worker, args=(mode,), daemon=True)
            self._thread.start()
            return self.snapshot()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            if self._mode == "paused":
                return self.snapshot()
            self._pause_requested = True
            if self._mode.startswith("running_"):
                self._resume_mode = self._mode.removeprefix("running_")
                self._mode = "pausing"
                self._events.append("runner", "Pause requested")
                process = self._process
            else:
                self._mode = "paused"
                process = None
        if process is not None and process.poll() is None:
            try:
                process.send_signal(signal.SIGINT)
            except Exception:  # noqa: BLE001
                pass
        return self.snapshot()

    def resume(self) -> dict[str, Any]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._pause_requested = False
                if self._mode == "paused" and self._resume_mode:
                    self._mode = f"running_{self._resume_mode}"
                self._events.append("runner", f"Resume requested: {self._resume_mode or 'full_auto'}")
                return self.snapshot()

            if self._mode == "paused" and self._memory.get_active_run_info() is not None:
                mode = self._resume_mode or "full_auto"
                self._pause_requested = False
                self._stop_requested = False
                self._mode = f"running_{mode}"
                self._events.append("runner", f"Resume requested: {mode}")
                self._thread = threading.Thread(target=self._worker, args=(mode,), daemon=True)
                self._thread.start()
                return self.snapshot()

            mode = self._resume_mode or "full_auto"
        return self.start(mode)

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop_requested = True
            self._pause_requested = False
            self._mode = "stopping"
            self._events.append("runner", "Stop requested")
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.send_signal(signal.SIGINT)
            except Exception:  # noqa: BLE001
                pass
        return self.snapshot()

    def _create_session_dir(self) -> Path:
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        session_dir = LOG_ROOT / time.strftime("%Y%m%d-%H%M%S")
        session_dir.mkdir(parents=True, exist_ok=True)
        latest = LOG_ROOT / "latest"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(session_dir.name)
        except OSError:
            pass
        return session_dir

    def _worker(self, mode: str) -> None:
        continuous = mode == "full_auto"
        cooldown = 0.0
        try:
            while True:
                with self._lock:
                    if self._stop_requested:
                        break
                    if self._pause_requested:
                        self._mode = "paused"
                        break
                    self._iteration += 1
                    iteration = self._iteration
                    self._current_iteration = iteration
                    self._live_thinking = ""
                    self._live_output = ""
                    self._active_tools.clear()
                    self._tool_commands.clear()
                    self._skills_used_this_iteration = set()
                    self._mode = f"running_{mode}"

                exit_code = self._run_one_iteration(iteration, mode)

                with self._lock:
                    self._last_exit_code = exit_code
                    self._current_iteration = None
                    paused = self._pause_requested
                    stopped = self._stop_requested

                if stopped:
                    break
                if paused:
                    with self._lock:
                        self._mode = "paused"
                    break
                if not continuous:
                    break
                if exit_code != 0:
                    break
                if cooldown > 0:
                    time.sleep(cooldown)
        finally:
            with self._lock:
                if self._stop_requested:
                    self._mode = "idle"
                elif self._pause_requested:
                    self._mode = "paused"
                elif mode == "single":
                    self._mode = "idle"
                elif self._mode != "paused":
                    self._mode = "idle"
                self._process = None
                self._thread = None
                self._stop_requested = False

    def _run_one_iteration(self, iteration: int, mode: str) -> int:
        env = self._build_runtime_env()
        sts2_bin = env.get("STS2_BIN", "")
        if sts2_bin and sts2_bin != self._last_reported_sts2_bin:
            self._events.append("runner", f"Resolved sts2: {sts2_bin}", {"sts2_bin": sts2_bin})
            self._last_reported_sts2_bin = sts2_bin
        pi_bin = resolve_pi_bin(env)
        if not os.path.isfile(pi_bin) or not os.access(pi_bin, os.X_OK):
            self._last_error = (
                f"pi runtime is not installed. Expected {PI_PACKAGE_NAME}@{PI_PACKAGE_VERSION}. "
                f"Run: bash {PI_SETUP_SCRIPT}"
            )
            self._events.append("error", self._last_error)
            return 1
        ok, initial_state, error = self.safe_fetch_state()
        if not ok:
            self._last_error = error or "sts2 state failed"
            self._events.append("error", self._last_error)
            return 1
        if initial_state is not None and self._tracked_state_summary is None:
            self._tracked_state_summary = summarize_state(initial_state)
        if initial_state is not None:
            self._memory.record_state(initial_state, raw_state=self._last_raw_state, source="iteration_start")
            self._memory.prepare_turn(iteration, mode=mode, state=initial_state)
        active_run_before = self._memory.get_active_run_info()
        last_run_before = self._memory.get_last_run_info()

        if active_run_before is not None:
            iter_dir = Path(active_run_before["data_dir"]) / "iterations" / f"{iteration:04d}"
            prompt_path = Path(active_run_before["data_dir"]) / "runtime_prompt.md"
        else:
            iter_dir = self._session_dir / "iterations" / f"{iteration:04d}"
            prompt_path = self._session_dir / "runtime_prompt.md"
        iter_dir.mkdir(parents=True, exist_ok=True)
        raw_path = iter_dir / "pi.raw.jsonl"
        text_path = iter_dir / "pi.log"
        prompt_text = self._build_prompt_text(mode)
        prompt_path.write_text(prompt_text, encoding="utf-8")
        self._events.append("runner", f"Iteration {iteration:04d} started")

        provider = env.get("PI_PROVIDER", "openrouter")
        model = env.get("PI_MODEL", "auto")

        cmd = [
            pi_bin,
            "--print",
            "--mode",
            "json",
            "--no-session",
            "--no-extensions",
            "--no-prompt-templates",
            "--no-themes",
            "--no-skills",
            "--skill",
            str(SKILL_PATH),
            "--append-system-prompt",
            str(APPEND_PROMPT),
            "--tools",
            "read,bash,grep,find,ls",
            "--provider",
            provider,
            "--model",
            model,
            prompt_text,
        ]

        parser = PiEventParser()
        microstep_tool_call_id: str | None = None
        microstep_stop_requested = False
        with raw_path.open("w", encoding="utf-8") as raw_file, text_path.open("w", encoding="utf-8") as text_file:
            process = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            with self._lock:
                self._process = process

            assert process.stdout is not None
            for line in process.stdout:
                raw_file.write(line)
                raw_file.flush()
                for parsed in parser.parse_line(line):
                    self._record_pi_event(parsed, text_file)
                    if mode == "single":
                        sts2_command = normalize_sts2_command(extract_bash_command(parsed.data))
                        if parsed.kind == "tool_start" and sts2_command and microstep_tool_call_id is None:
                            microstep_tool_call_id = str(parsed.data.get("toolCallId") or "")
                        elif (
                            parsed.kind in {"tool_end", "tool_error"}
                            and microstep_tool_call_id
                            and str(parsed.data.get("toolCallId") or "") == microstep_tool_call_id
                            and not microstep_stop_requested
                        ):
                            microstep_stop_requested = True
                            try:
                                process.send_signal(signal.SIGINT)
                            except Exception:  # noqa: BLE001
                                pass

            exit_code = process.wait()

        with self._lock:
            self._process = None

        self._finalize_iteration_artifacts(
            iteration=iteration,
            mode=mode,
            prompt_text=prompt_text,
            prompt_path=prompt_path,
            raw_path=raw_path,
            text_path=text_path,
            active_run_before=active_run_before,
            last_run_before=last_run_before,
        )

        ok, state, error = self.safe_fetch_state()
        if ok and state is not None:
            self._memory.record_state(state, raw_state=self._last_raw_state, source="iteration_end")
            self._emit_state_change_events(state)
            self._events.append("state", json.dumps(summarize_state(state), ensure_ascii=False), summarize_state(state))
        elif error:
            self._events.append("state_error", error)

        if microstep_stop_requested and exit_code == 130:
            exit_code = 0

        if exit_code != 0 and not self._pause_requested and not self._stop_requested:
            self._last_error = f"pi exit code {exit_code}"
            self._events.append("error", self._last_error, {"exit_code": exit_code})
        self._events.append("runner", f"Iteration {iteration:04d} exit code {exit_code}", {"exit_code": exit_code})
        return exit_code

    def _finalize_iteration_artifacts(
        self,
        *,
        iteration: int,
        mode: str,
        prompt_text: str,
        prompt_path: Path,
        raw_path: Path,
        text_path: Path,
        active_run_before: dict[str, Any] | None,
        last_run_before: dict[str, Any] | None,
    ) -> None:
        run_info = self._resolve_iteration_run_info(active_run_before=active_run_before, last_run_before=last_run_before)
        if run_info is None:
            return

        data_dir = Path(run_info["data_dir"])
        target_iter_dir = data_dir / "iterations" / f"{iteration:04d}"
        target_iter_dir.mkdir(parents=True, exist_ok=True)
        target_raw = self._move_artifact_file(raw_path, target_iter_dir / "pi.raw.jsonl")
        target_text = self._move_artifact_file(text_path, target_iter_dir / "pi.log")
        target_prompt = self._memory.write_runtime_prompt(prompt_text, iteration=iteration, mode=mode)
        if target_prompt is not None and prompt_path != target_prompt and prompt_path.exists():
            prompt_path.unlink()
        self._memory.record_iteration_artifacts(iteration, raw_path=target_raw, text_path=target_text)

    def _resolve_iteration_run_info(
        self,
        *,
        active_run_before: dict[str, Any] | None,
        last_run_before: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        active_run_after = self._memory.get_active_run_info()
        if active_run_after is not None:
            return active_run_after

        last_run_after = self._memory.get_last_run_info()
        if last_run_after is None:
            return None

        if active_run_before is not None and last_run_after.get("run_id") == active_run_before.get("run_id"):
            return last_run_after

        if active_run_before is None and (
            last_run_before is None or last_run_after.get("run_id") != last_run_before.get("run_id")
        ):
            return last_run_after

        return None

    def _move_artifact_file(self, source: Path, target: Path) -> Path:
        if source == target:
            return target
        if not source.exists():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        shutil.move(str(source), str(target))
        try:
            source.parent.rmdir()
        except OSError:
            pass
        return target

    def _match_skill_for_path(self, path: Path) -> dict[str, str] | None:
        for skill in self._loaded_skills:
            base_dir = Path(skill["base_dir"])
            if path_is_within(path, base_dir):
                return skill
        return None

    def _record_skill_invocation(self, skill: dict[str, str], *, path: Path) -> None:
        skill_name = skill["name"]
        self._skills_used_this_iteration.add(skill_name)
        item = {
            "ts": time.time(),
            "iteration": self._current_iteration,
            "skill_name": skill_name,
            "path": str(path),
            "description": skill.get("description", ""),
        }
        self._recent_skill_invocations.appendleft(item)
        self._events.append("skill", f"{skill_name} read from {path.name}", item)

    def _record_memory_fetch(
        self,
        *,
        source: str,
        label: str,
        path: str | None = None,
        command: str | None = None,
        preview: str = "",
    ) -> None:
        category = classify_memory_target(path=path, command=command)
        item = {
            "ts": time.time(),
            "iteration": self._current_iteration,
            "source": source,
            "label": label,
            "category": category,
            "path": path,
            "command": command,
            "preview": summarize_preview(preview),
            "via_memory_skill": MEMORY_SKILL_NAME in self._skills_used_this_iteration,
            "via_memory_v3_skill": MEMORY_V3_SKILL_NAME in self._skills_used_this_iteration,
        }
        self._recent_memory_fetches.appendleft(item)
        timeline_text = f"[{category}] {label}"
        if path:
            timeline_text += f" [{Path(path).name}]"
        self._events.append("memory_fetch", timeline_text, item)

    def _record_pi_event(self, event: ParsedPiEvent, text_file: Any) -> None:
        tool_call_id = str(event.data.get("toolCallId") or "")
        tool_name = str(event.data.get("toolName") or "")
        shell_command = extract_bash_command(event.data)
        read_path = extract_read_path(event.data)
        if event.kind == "tool_start" and tool_call_id and shell_command:
            self._tool_commands[tool_call_id] = shell_command
        elif not shell_command and tool_call_id:
            shell_command = self._tool_commands.get(tool_call_id)
        pending_sts2_commands = [
            segment.removeprefix("sts2 ").strip()
            for segment in extract_sts2_segments(shell_command)
        ]
        self._events.append(event.kind, event.text, event.data)
        self._memory.record_agent_event(event.kind, event.text, data=event.data)
        if event.kind == "thinking_delta":
            with self._lock:
                self._live_thinking += event.text
        elif event.kind == "assistant_text_delta":
            with self._lock:
                self._live_output += event.text
        elif event.kind == "assistant_done":
            with self._lock:
                if not self._live_output:
                    self._live_output = event.text
        elif event.kind == "tool_start":
            with self._lock:
                self._active_tools.append({"name": event.text, "status": "running"})
            for command_text in pending_sts2_commands:
                self._events.append("sts2_command", command_text, event.data)
                self._recent_commands.append(command_text)
        elif event.kind in {"tool_end", "tool_error"}:
            with self._lock:
                if self._active_tools:
                    self._active_tools[-1]["status"] = "done" if event.kind == "tool_end" else "error"
                    self._active_tools[-1]["result"] = event.text
            result_text = extract_text(event.data.get("result")) or event.text
            if event.kind == "tool_end" and bash_command_succeeded(result_text):
                for command_text in pending_sts2_commands:
                    deferred = self._memory.ensure_run_from_command(command_text, source="agent", result=event.text)
                    if not deferred:
                        self._memory.record_command(command_text, result=event.text, source="agent")
            if event.kind == "tool_end" and tool_name == "read" and read_path is not None:
                skill = self._match_skill_for_path(read_path)
                if skill is not None:
                    self._record_skill_invocation(skill, path=read_path)
                if path_is_within(read_path, MEMORY_ROOT):
                    self._record_memory_fetch(
                        source="read",
                        label="Read memory file",
                        path=str(read_path),
                        preview=result_text,
                    )
            if (
                event.kind == "tool_end"
                and tool_name == "bash"
                and shell_command
                and ("memory/" in shell_command or "index.sqlite" in shell_command)
            ):
                label = "Queried memory archive" if "sqlite3" in shell_command else "Read memory via bash"
                self._record_memory_fetch(
                    source="bash",
                    label=label,
                    command=shell_command,
                    preview=result_text,
                )
            if has_sts2_subcommand(shell_command, "state"):
                parsed_state = parse_sts2_state_output(result_text)
                if parsed_state is not None:
                    self._memory.record_state(parsed_state, raw_state=None, source="agent_state_command")
            if tool_call_id:
                self._tool_commands.pop(tool_call_id, None)
        elif event.kind == "log":
            with self._lock:
                self._last_warning = event.text
        text_file.write(f"[{event.kind}] {event.text}\n")
        text_file.flush()

    def _emit_state_change_events(self, state: dict[str, Any]) -> None:
        summary = summarize_state(state)
        if not summary:
            return
        previous = self._tracked_state_summary
        self._tracked_state_summary = summary
        if previous is None:
            return

        if previous.get("decision") != summary.get("decision"):
            text = f"{previous.get('decision') or '-'} -> {summary.get('decision') or '-'}"
            self._events.append("state_transition", text, {"from": previous.get("decision"), "to": summary.get("decision")})

        if previous.get("hp") != summary.get("hp") or previous.get("max_hp") != summary.get("max_hp"):
            old_hp = previous.get("hp")
            new_hp = summary.get("hp")
            old_max = previous.get("max_hp")
            new_max = summary.get("max_hp")
            delta_text = ""
            if isinstance(old_hp, (int, float)) and isinstance(new_hp, (int, float)):
                delta = int(new_hp - old_hp)
                if delta != 0:
                    delta_text = f" ({delta:+d})"
            text = f"{old_hp} / {old_max} -> {new_hp} / {new_max}{delta_text}"
            self._events.append("hp_change", text, {"from": [old_hp, old_max], "to": [new_hp, new_max]})

        if previous.get("floor") != summary.get("floor"):
            text = f"{previous.get('floor') or '-'} -> {summary.get('floor') or '-'}"
            self._events.append("floor_change", text, {"from": previous.get("floor"), "to": summary.get("floor")})

        if previous.get("act") != summary.get("act"):
            text = f"{previous.get('act') or '-'} -> {summary.get('act') or '-'}"
            self._events.append("act_change", text, {"from": previous.get("act"), "to": summary.get("act")})

        if previous.get("gold") != summary.get("gold"):
            old_gold = previous.get("gold")
            new_gold = summary.get("gold")
            delta_text = ""
            if isinstance(old_gold, (int, float)) and isinstance(new_gold, (int, float)):
                delta = int(new_gold - old_gold)
                if delta != 0:
                    delta_text = f" ({delta:+d})"
            text = f"{old_gold} -> {new_gold}{delta_text}"
            self._events.append("gold_change", text, {"from": old_gold, "to": new_gold})

    def _build_runtime_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(load_env_file(ENV_FILE))
        path_entries = [str(ROOT), "/opt/homebrew/bin"]
        existing_path = env.get("PATH", "")
        if existing_path:
            path_entries.append(existing_path)
        env["PATH"] = ":".join(path_entries)
        env["STS2CLI_ROOT"] = str(ROOT)
        env["STS2_BIN"] = resolve_sts2_bin(env)
        env["PI_CODING_AGENT_DIR"] = env.get("PI_CODING_AGENT_DIR", str(ROOT / ".agents" / "pi-home"))
        Path(env["PI_CODING_AGENT_DIR"]).mkdir(parents=True, exist_ok=True)
        self._write_models_json_override(env)
        return env

    def _write_models_json_override(self, env: dict[str, str]) -> None:
        provider = env.get("PI_PROVIDER", "openrouter")
        base_url = env.get("PI_BASE_URL", "")
        if not base_url:
            return
        api_key_env = env.get("PI_API_KEY_ENV") or derive_api_key_env(provider)
        if not api_key_env:
            raise RuntimeError("PI_API_KEY_ENV is required when PI_BASE_URL is set")
        models_path = Path(env["PI_CODING_AGENT_DIR"]) / "models.json"
        payload = {
            "providers": {
                provider: {
                    "baseUrl": base_url,
                    "apiKey": api_key_env,
                }
            }
        }
        models_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_prompt_text(self, mode: str) -> str:
        memory_context = self._memory.get_prompt_context()
        common = BASE_PROMPT_PATH.read_text(encoding="utf-8").strip() + "\n"
        if memory_context:
            common += (
                "\nShort-term run memory is available under `STS2CLI/memory/runs/<run_id>/memory/summary.md`.\n"
                "Use the following current-run summary as additional context:\n\n"
                f"{memory_context}\n"
            )
        if mode == "single":
            return (
                common
                + "- This is MICRO-STEP mode.\n"
                + "- In this invocation, execute at most one `sts2` command that changes game state.\n"
                + "- You may read state before acting, but after one state-changing `sts2` command, stop immediately.\n"
            )
        return (
            common
            + "- This is FULL-AUTO mode.\n"
            + "- During this invocation, make forward progress until you reach a stable pause point after resolving obvious follow-up actions.\n"
        )


CONTROLLER = AgentController()


class FrontendHandler(BaseHTTPRequestHandler):
    server_version = "STS2CLIFrontend/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        if parsed.path.startswith("/static/"):
            rel = parsed.path.removeprefix("/static/")
            target = STATIC_DIR / rel
            content_type = "text/plain; charset=utf-8"
            if target.suffix == ".js":
                content_type = "application/javascript; charset=utf-8"
            elif target.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            return self._serve_file(target, content_type)
        if parsed.path == "/api/status":
            return self._send_json(CONTROLLER.snapshot())
        if parsed.path == "/api/state":
            try:
                return self._send_json(CONTROLLER.fetch_state())
            except Exception as exc:  # noqa: BLE001
                return self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_GATEWAY)
        if parsed.path == "/api/events":
            params = parse_qs(parsed.query)
            after = int(params.get("after", ["0"])[0])
            return self._send_json({"events": CONTROLLER.list_events(after)})
        if parsed.path == "/api/memory/search":
            params = parse_qs(parsed.query)
            flat = {key: values[0] for key, values in params.items() if values}
            try:
                return self._send_json(CONTROLLER.search_memory_runs(flat))
            except Exception as exc:  # noqa: BLE001
                return self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if parsed.path == "/api/memory/run":
            params = parse_qs(parsed.query)
            run_id = params.get("run_id", [""])[0].strip()
            if not run_id:
                return self._send_json({"ok": False, "error": "run_id is required"}, HTTPStatus.BAD_REQUEST)
            try:
                return self._send_json(CONTROLLER.get_memory_run_detail(run_id))
            except Exception as exc:  # noqa: BLE001
                return self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if parsed.path == "/api/memory/stats":
            params = parse_qs(parsed.query)
            flat = {key: values[0] for key, values in params.items() if values}
            try:
                return self._send_json(CONTROLLER.get_memory_stats(flat))
            except Exception as exc:  # noqa: BLE001
                return self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if parsed.path == "/api/memory/v3/status":
            return self._send_json(CONTROLLER.get_memory_v3_status())
        if parsed.path == "/api/memory/v3/search":
            params = parse_qs(parsed.query)
            flat = {key: values[0] for key, values in params.items() if values}
            try:
                return self._send_json(CONTROLLER.search_memory_v3(flat))
            except Exception as exc:  # noqa: BLE001
                return self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if parsed.path == "/api/memory/v3/file":
            params = parse_qs(parsed.query)
            rel_path = params.get("path", [""])[0].strip()
            if not rel_path:
                return self._send_json({"ok": False, "error": "path is required"}, HTTPStatus.BAD_REQUEST)
            try:
                return self._send_json(CONTROLLER.get_memory_v3_file(rel_path))
            except Exception as exc:  # noqa: BLE001
                return self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return self._send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        body = self._read_json_body()
        try:
            if parsed.path == "/api/agent/start":
                mode = str(body.get("mode") or "full_auto")
                return self._send_json({"ok": True, "status": CONTROLLER.start(mode)})
            if parsed.path == "/api/agent/pause":
                return self._send_json({"ok": True, "status": CONTROLLER.pause()})
            if parsed.path == "/api/agent/resume":
                return self._send_json({"ok": True, "status": CONTROLLER.resume()})
            if parsed.path == "/api/agent/stop":
                return self._send_json({"ok": True, "status": CONTROLLER.stop()})
        except Exception as exc:  # noqa: BLE001
            return self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return self._send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            return self._send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local browser control panel for STS2CLI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), FrontendHandler)
    print(f"STS2CLI frontend available at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down frontend server...", flush=True)
    finally:
        CONTROLLER.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
