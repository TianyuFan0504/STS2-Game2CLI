from __future__ import annotations

import re
import shlex
from pathlib import Path

_ENV_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")


def normalize_sts2_command(command: str | None) -> str | None:
    segments = extract_sts2_segments(command)
    if not segments:
        return None
    return segments[0]


def extract_sts2_segments(command: str | None) -> list[str]:
    if not command:
        return []

    segments: list[str] = []
    for tokens in _split_shell_segments(command):
        canonical = _canonicalize_sts2_tokens(tokens)
        if canonical is not None:
            segments.append(canonical)
    return segments


def has_sts2_subcommand(command: str | None, subcommand: str) -> bool:
    prefix = f"sts2 {subcommand}"
    return any(segment == prefix or segment.startswith(f"{prefix} ") for segment in extract_sts2_segments(command))


def _split_shell_segments(command: str) -> list[list[str]]:
    segments: list[list[str]] = []
    for raw_line in command.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|")
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            segments.append([line])
            continue

        current: list[str] = []
        for token in tokens:
            if token in {";", "&&", "||", "|", "&"}:
                if current:
                    segments.append(current)
                    current = []
                continue
            current.append(token)
        if current:
            segments.append(current)
    return segments


def _canonicalize_sts2_tokens(tokens: list[str]) -> str | None:
    command_index = _command_index(tokens)
    if command_index is None:
        return None

    command = tokens[command_index]
    if _path_name(command) == "sts2":
        return shlex.join(["sts2", *tokens[command_index + 1 :]])

    if _looks_like_python(command):
        cli_args = _extract_python_cli_args(tokens, command_index)
        if cli_args is not None:
            return shlex.join(["sts2", *cli_args])

    return None


def _command_index(tokens: list[str]) -> int | None:
    if not tokens:
        return None

    index = 0
    if tokens[index] == "env":
        index += 1
    while index < len(tokens) and _ENV_ASSIGNMENT_RE.fullmatch(tokens[index]):
        index += 1
    if index >= len(tokens):
        return None
    return index


def _looks_like_python(token: str) -> bool:
    name = _path_name(token)
    return name == "python" or name.startswith("python")


def _extract_python_cli_args(tokens: list[str], command_index: int) -> list[str] | None:
    next_index = command_index + 1
    if next_index >= len(tokens):
        return None

    launcher = tokens[next_index]
    if launcher == "-m" and next_index + 1 < len(tokens) and tokens[next_index + 1] == "sts2cli.cli":
        return tokens[next_index + 2 :]

    if launcher == "-c" and next_index + 1 < len(tokens) and _looks_like_inline_sts2_cli(tokens[next_index + 1]):
        return tokens[next_index + 2 :]

    if _looks_like_sts2_cli_script(launcher):
        return tokens[next_index + 1 :]

    return None


def _looks_like_inline_sts2_cli(script: str) -> bool:
    return "sts2cli.cli" in script and "main()" in script


def _looks_like_sts2_cli_script(token: str) -> bool:
    normalized = token.replace("\\", "/")
    return normalized.endswith("/sts2cli/cli.py") or normalized == "sts2cli/cli.py"


def _path_name(token: str) -> str:
    return Path(token).name
