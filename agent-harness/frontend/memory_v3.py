#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any


class MemoryV3Workspace:
    def __init__(self, root: Path):
        self.root = root
        self.workspace_dir = root / "global_memory"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        files = self._markdown_files()
        invalid = self._invalid_files()
        return {
            "root": str(self.workspace_dir),
            "file_count": len(files),
            "invalid_file_count": len(invalid),
            "invalid_files": [self._display_relative(path) for path in invalid[:50]],
            "files": [self._file_info(path) for path in files[:50]],
        }

    def search(self, *, query: str | None = None, limit: int = 50) -> dict[str, Any]:
        text = (query or "").strip().lower()
        limit = max(1, min(limit, 200))
        results: list[dict[str, Any]] = []
        for path in self._markdown_files():
            content = self._read_text(path)
            haystacks = [self._display_relative(path).lower(), content.lower()]
            if text and not any(text in haystack for haystack in haystacks):
                continue
            results.append(
                {
                    **self._file_info(path),
                    "preview": self._preview(content),
                }
            )
            if len(results) >= limit:
                break
        return {
            "root": str(self.workspace_dir),
            "query": query or "",
            "results": results,
        }

    def read_file(self, relative_path: str) -> dict[str, Any]:
        path = self._resolve_markdown_path(relative_path)
        return {
            "root": str(self.workspace_dir),
            "path": self._display_relative(path),
            "content": self._read_text(path),
            "info": self._file_info(path),
        }

    def _markdown_files(self) -> list[Path]:
        files = [path for path in self.workspace_dir.rglob("*.md") if path.is_file()]
        return sorted(files, key=lambda path: self._display_relative(path))

    def _invalid_files(self) -> list[Path]:
        files = [path for path in self.workspace_dir.rglob("*") if path.is_file() and path.suffix.lower() != ".md"]
        return sorted(files, key=lambda path: self._display_relative(path))

    def _resolve_markdown_path(self, relative_path: str) -> Path:
        candidate = (self.workspace_dir / relative_path).resolve()
        workspace = self.workspace_dir.resolve()
        try:
            candidate.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {relative_path}") from exc
        if candidate.suffix.lower() != ".md":
            raise ValueError("Only .md files are allowed in Memory V3")
        if not candidate.exists() or not candidate.is_file():
            raise ValueError(f"Markdown file not found: {relative_path}")
        return candidate

    def _display_relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.workspace_dir.resolve()))
        except ValueError:
            return str(path)

    def _file_info(self, path: Path) -> dict[str, Any]:
        stats = path.stat()
        return {
            "path": self._display_relative(path),
            "size_bytes": stats.st_size,
            "modified_ts": stats.st_mtime,
        }

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _preview(self, text: str, limit: int = 400) -> str:
        compact = text.strip()
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3] + "..."
