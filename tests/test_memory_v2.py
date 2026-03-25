from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "agent-harness" / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from memory_v1 import MemoryV1Store


def build_state(
    decision: str,
    *,
    state_type: str,
    act: int = 1,
    floor: int = 1,
    ascension: int = 0,
    hp: int = 80,
    max_hp: int = 80,
    gold: int = 99,
    **extra: Any,
) -> dict[str, Any]:
    state = {
        "type": state_type,
        "decision": decision,
        "context": {
            "act": act,
            "floor": floor,
            "ascension": ascension,
        },
        "player": {
            "character": "IRONCLAD",
            "hp": hp,
            "max_hp": max_hp,
            "gold": gold,
        },
    }
    state.update(extra)
    return state


class MemoryV2ArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "memory"
        self.store = MemoryV1Store(self.root)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_finalized_run_generates_v2_derived_files_and_archive_index(self) -> None:
        self.store.record_state(
            build_state(
                "map_select",
                state_type="decision",
                visited=[{"col": 0, "row": 0, "type": "start"}],
                current_position={"col": 0, "row": 0, "type": "start"},
                choices=[],
            ),
            source="iteration_start",
        )
        run_id = self.store.get_active_run_info()["run_id"]

        self.store.record_command("choose-map 0", result="ok", source="agent")
        self.store.record_state(
            build_state(
                "combat_play",
                state_type="decision",
                floor=2,
                hp=75,
                max_hp=80,
                gold=120,
                hand=[],
                enemies=[],
            ),
            source="iteration_end",
        )
        self.store.finalize_if_active("won")

        run_dir = self.root / "runs" / run_id
        self.assertTrue((run_dir / "turns").is_dir())
        self.assertTrue((run_dir / "battles").is_dir())
        self.assertTrue((run_dir / "rewards").is_dir())
        self.assertTrue((run_dir / "derived").is_dir())

        route_timeline = json.loads((run_dir / "derived" / "route_timeline.json").read_text(encoding="utf-8"))
        self.assertEqual(route_timeline["run_id"], run_id)
        self.assertEqual(route_timeline["entries"][0]["type"], "start")

        resource_timeline = json.loads((run_dir / "derived" / "resource_timeline.json").read_text(encoding="utf-8"))
        self.assertEqual(resource_timeline["final"]["result"], "won")
        event_types = [entry["event_type"] for entry in resource_timeline["entries"]]
        self.assertIn("hp_change", event_types)
        self.assertIn("gold_change", event_types)
        self.assertIn("floor_change", event_types)

        run_tags = json.loads((run_dir / "derived" / "run_tags.json").read_text(encoding="utf-8"))
        tags = {(tag["tag_type"], tag["tag_value"]) for tag in run_tags["tags"]}
        self.assertIn(("character", "IRONCLAD"), tags)
        self.assertIn(("result", "won"), tags)

        archive_runs = self.store.v2.find_runs(character="IRONCLAD")
        self.assertEqual(len(archive_runs), 1)
        self.assertEqual(archive_runs[0]["run_id"], run_id)
        self.assertEqual(archive_runs[0]["result"], "won")

        tagged_runs = self.store.v2.find_runs_by_tag("result", "won")
        self.assertEqual(len(tagged_runs), 1)
        self.assertEqual(tagged_runs[0]["run_id"], run_id)


if __name__ == "__main__":
    unittest.main()
