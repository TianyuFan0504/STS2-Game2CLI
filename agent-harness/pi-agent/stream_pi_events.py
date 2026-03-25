#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Any


class EventPrinter:
    def __init__(self) -> None:
        self._text_stream_open = False
        self._assistant_had_text = False

    def process_line(self, raw_line: str) -> None:
        line = raw_line.rstrip("\n")
        if not line:
            return

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            self._flush_text_stream()
            print(line, flush=True)
            return

        event_type = event.get("type")

        if event_type == "message_update":
            self._handle_message_update(event)
            return

        if event_type == "message_start":
            message = event.get("message")
            if isinstance(message, dict) and message.get("role") == "assistant":
                self._assistant_had_text = False
            return

        if event_type == "message_end":
            self._handle_message_end(event)
            return

        if event_type == "tool_execution_start":
            self._flush_text_stream()
            tool_name = str(event.get("toolName") or "tool")
            args = _short_json(event.get("args"))
            print(f"[tool:start] {tool_name} {args}".rstrip(), flush=True)
            return

        if event_type == "tool_execution_update":
            partial = _extract_text(event.get("partialResult"))
            if partial:
                self._flush_text_stream()
                print(f"[tool:update] {partial}", flush=True)
            return

        if event_type == "tool_execution_end":
            self._flush_text_stream()
            tool_name = str(event.get("toolName") or "tool")
            status = "error" if event.get("isError") else "ok"
            result_text = _extract_text(event.get("result")) or _short_json(event.get("result"))
            if result_text:
                print(f"[tool:{status}] {tool_name} {result_text}", flush=True)
            else:
                print(f"[tool:{status}] {tool_name}", flush=True)
            return

        if event_type in {"agent_start", "agent_end", "turn_start", "turn_end", "session"}:
            self._flush_text_stream()
            return

        self._flush_text_stream()
        print(line, flush=True)

    def finish(self) -> None:
        self._flush_text_stream()

    def _handle_message_update(self, event: dict[str, Any]) -> None:
        assistant_event = event.get("assistantMessageEvent")
        if not isinstance(assistant_event, dict):
            return

        update_type = assistant_event.get("type")
        if update_type == "text_delta":
            delta = assistant_event.get("delta")
            if isinstance(delta, str) and delta:
                sys.stdout.write(delta)
                sys.stdout.flush()
                self._text_stream_open = True
                self._assistant_had_text = True
        elif update_type == "text_end":
            self._flush_text_stream()

    def _handle_message_end(self, event: dict[str, Any]) -> None:
        message = event.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return

        if self._text_stream_open:
            self._flush_text_stream()
            self._assistant_had_text = False
            return

        if self._assistant_had_text:
            self._assistant_had_text = False
            return

        text = _assistant_text(message)
        if text:
            print(text, flush=True)

    def _flush_text_stream(self) -> None:
        if self._text_stream_open:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._text_stream_open = False


def _assistant_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
    return "".join(parts)


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "stdout", "stderr", "message", "content"):
            child = value.get(key)
            extracted = _extract_text(child)
            if extracted:
                return extracted
    if isinstance(value, list):
        parts = [_extract_text(item) for item in value]
        joined = " ".join(part for part in parts if part)
        return joined.strip()
    return ""


def _short_json(value: Any, limit: int = 240) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except TypeError:
        text = repr(value)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def main() -> int:
    printer = EventPrinter()
    try:
        for line in sys.stdin:
            printer.process_line(line)
    finally:
        printer.finish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
