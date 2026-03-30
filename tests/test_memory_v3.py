from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "agent-harness" / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from memory_v3 import MemoryV3Workspace


class MemoryV3WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.memory_root = Path(self.tempdir.name) / "memory"
        self.workspace = MemoryV3Workspace(self.memory_root)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_workspace_is_created_and_reports_markdown_files(self) -> None:
        notes_dir = self.workspace.workspace_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (self.workspace.workspace_dir / "root.md").write_text("# Root\nhello\n", encoding="utf-8")
        (notes_dir / "enemy.md").write_text("Lagavulin note\n", encoding="utf-8")
        (notes_dir / "temp.txt").write_text("not allowed\n", encoding="utf-8")

        status = self.workspace.status()
        self.assertEqual(status["file_count"], 2)
        self.assertEqual(status["invalid_file_count"], 1)
        file_paths = [item["path"] for item in status["files"]]
        self.assertEqual(file_paths, ["notes/enemy.md", "root.md"])
        self.assertEqual(status["invalid_files"], ["notes/temp.txt"])

    def test_search_and_read_file(self) -> None:
        (self.workspace.workspace_dir / "bosses").mkdir(parents=True, exist_ok=True)
        (self.workspace.workspace_dir / "bosses" / "hexaghost.md").write_text(
            "Hexaghost is dangerous when HP is low.\n",
            encoding="utf-8",
        )
        (self.workspace.workspace_dir / "journal.md").write_text(
            "Need to remember Jaw Worm openers.\n",
            encoding="utf-8",
        )

        search = self.workspace.search(query="jaw worm")
        self.assertEqual(len(search["results"]), 1)
        self.assertEqual(search["results"][0]["path"], "journal.md")

        file_payload = self.workspace.read_file("bosses/hexaghost.md")
        self.assertEqual(file_payload["path"], "bosses/hexaghost.md")
        self.assertIn("Hexaghost", file_payload["content"])

    def test_read_rejects_non_markdown_and_path_escape(self) -> None:
        (self.workspace.workspace_dir / "notes.md").write_text("ok\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.workspace.read_file("../notes.md")
        with self.assertRaises(ValueError):
            self.workspace.read_file("notes.txt")


if __name__ == "__main__":
    unittest.main()
