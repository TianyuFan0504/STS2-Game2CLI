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
from sts2_commands import extract_sts2_segments

PYTHON_FALLBACK_START = (
    'python3 -c "import sys; sys.path.insert(0, \'.\'); '
    'from sts2cli.cli import main; main()" start-game --character IRONCLAD --ascension 0'
)


def build_state(
    decision: str,
    *,
    state_type: str,
    act: int = 1,
    floor: int = 1,
    ascension: int = 0,
    character: str | None = "IRONCLAD",
    hp: int | None = 80,
    max_hp: int | None = 80,
    gold: int | None = 99,
    **extra: Any,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "type": state_type,
        "decision": decision,
        "context": {
            "act": act,
            "floor": floor,
            "ascension": ascension,
        },
    }
    if character is not None or hp is not None or max_hp is not None or gold is not None:
        state["player"] = {
            "character": character,
            "hp": hp,
            "max_hp": max_hp,
            "gold": gold,
        }
    state.update(extra)
    return state


class MemoryV1StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "memory"
        self.store = MemoryV1Store(self.root)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _active_run_id(self) -> str:
        info = self.store.get_active_run_info()
        self.assertIsNotNone(info)
        assert info is not None
        return str(info["run_id"])

    def _run_dir(self, run_id: str) -> Path:
        return self.root / "runs" / run_id

    def _load_session(self, run_id: str) -> dict[str, Any]:
        return json.loads((self._run_dir(run_id) / "data" / "session.json").read_text(encoding="utf-8"))

    def _load_events(self, run_id: str) -> list[dict[str, Any]]:
        lines = (self._run_dir(run_id) / "data" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def _load_summary(self, run_id: str) -> str:
        return (self._run_dir(run_id) / "memory" / "summary.md").read_text(encoding="utf-8")

    def test_active_run_is_restored_after_returning_to_menu(self) -> None:
        self.store.record_state(
            build_state(
                "map_select",
                state_type="decision",
                current_position={"col": 0, "row": 0, "type": "start"},
                choices=[],
                visited=[],
            ),
            source="iteration_start",
        )
        run_id = self._active_run_id()

        self.store.record_state(
            build_state(
                "menu",
                state_type="status",
                floor=2,
                can_continue_game=True,
                can_start_new_game=True,
                menu={"screen": "main_menu"},
            ),
            source="iteration_end",
        )

        active_info = self.store.get_active_run_info()
        self.assertIsNotNone(active_info)
        assert active_info is not None
        self.assertEqual(active_info["run_id"], run_id)
        self.assertEqual((self.root / "latest").resolve(strict=True).name, run_id)

        restored = MemoryV1Store(self.root)
        restored_info = restored.get_active_run_info()
        self.assertIsNotNone(restored_info)
        assert restored_info is not None
        self.assertEqual(restored_info["run_id"], run_id)
        self.assertIn(run_id, restored.get_prompt_context())
        self.assertEqual(self._load_session(run_id)["status"], "active")

    def test_abandon_game_from_menu_finalizes_run(self) -> None:
        self.store.record_state(
            build_state(
                "map_select",
                state_type="decision",
                current_position={"col": 0, "row": 0, "type": "start"},
                choices=[],
                visited=[],
            ),
            source="iteration_start",
        )
        run_id = self._active_run_id()

        self.store.record_state(
            build_state(
                "menu",
                state_type="status",
                can_continue_game=True,
                can_start_new_game=True,
                menu={"screen": "main_menu"},
            ),
            source="iteration_end",
        )
        self.store.record_command("abandon-game", result="ok", source="agent")
        self.store.record_state(
            build_state(
                "menu",
                state_type="status",
                can_continue_game=False,
                can_start_new_game=True,
                menu={"screen": "main_menu"},
            ),
            source="iteration_end",
        )

        self.assertIsNone(self.store.get_active_run_info())
        self.assertEqual(self.store.get_last_run_info()["run_id"], run_id)

        session = self._load_session(run_id)
        self.assertEqual(session["result"], "abandoned")
        self.assertEqual(session["status"], "abandoned")
        self.assertEqual(session["last_command"], "abandon-game")

        summary = self._load_summary(run_id)
        self.assertIn("- Status: abandoned", summary)
        self.assertIn("- Result: abandoned", summary)

        events = self._load_events(run_id)
        self.assertEqual(events[-1]["event_type"], "run_ended")
        self.assertEqual(events[-1]["payload"]["result"], "abandoned")

    def test_game_over_result_survives_return_to_menu(self) -> None:
        self.store.record_state(
            build_state(
                "combat_play",
                state_type="decision",
                hp=23,
                max_hp=80,
                hand=[],
                enemies=[],
            ),
            source="iteration_start",
        )
        run_id = self._active_run_id()

        self.store.record_state(
            build_state(
                "game_over",
                state_type="decision",
                hp=0,
                max_hp=80,
                can_return_to_main_menu=True,
                can_continue=False,
                options=[{"id": "return_to_main_menu", "is_enabled": True}],
            ),
            source="iteration_end",
        )
        self.store.record_state(
            build_state(
                "menu",
                state_type="status",
                hp=0,
                max_hp=80,
                can_continue_game=False,
                can_start_new_game=True,
                menu={"screen": "main_menu"},
            ),
            source="iteration_end",
        )

        session = self._load_session(run_id)
        self.assertEqual(session["result"], "lost")
        self.assertEqual(session["status"], "lost")

    def test_python_cli_fallback_is_recognized_as_sts2_start_game(self) -> None:
        self.assertEqual(
            extract_sts2_segments(PYTHON_FALLBACK_START),
            ["sts2 start-game --character IRONCLAD --ascension 0"],
        )

    def test_python_cli_fallback_start_game_splits_run_after_game_over(self) -> None:
        self.store.record_state(
            build_state(
                "combat_play",
                state_type="decision",
                hp=23,
                max_hp=80,
                hand=[],
                enemies=[],
            ),
            source="iteration_start",
        )
        old_run_id = self._active_run_id()

        self.store.record_state(
            build_state(
                "game_over",
                state_type="decision",
                hp=0,
                max_hp=80,
                can_return_to_main_menu=True,
                can_continue=False,
                options=[{"id": "return_to_main_menu", "is_enabled": True}],
            ),
            source="iteration_end",
        )
        self.store.record_state(
            build_state(
                "menu",
                state_type="status",
                hp=0,
                max_hp=80,
                can_continue_game=False,
                can_start_new_game=True,
                menu={"screen": "main_menu"},
            ),
            source="iteration_end",
        )

        deferred = self.store.ensure_run_from_command(PYTHON_FALLBACK_START, source="agent", result="ok")
        self.assertTrue(deferred)

        self.store.record_state(
            build_state(
                "map_select",
                state_type="decision",
                floor=0,
                hp=80,
                max_hp=80,
                current_position={"col": 0, "row": 0, "type": "start"},
                choices=[],
                visited=[],
            ),
            source="iteration_start",
        )

        new_run_id = self._active_run_id()
        self.assertNotEqual(new_run_id, old_run_id)
        self.assertEqual((self.root / "latest").resolve(strict=True).name, new_run_id)

        old_session = self._load_session(old_run_id)
        self.assertEqual(old_session["status"], "lost")
        self.assertEqual(old_session["result"], "lost")

        new_session = self._load_session(new_run_id)
        self.assertEqual(new_session["status"], "active")
        self.assertEqual(new_session["last_command"], "start-game --character IRONCLAD --ascension 0")

    def test_finished_run_is_not_injected_back_into_prompt(self) -> None:
        self.store.record_state(
            build_state(
                "map_select",
                state_type="decision",
                current_position={"col": 0, "row": 0, "type": "start"},
                choices=[],
                visited=[],
            ),
            source="iteration_start",
        )
        run_id = self._active_run_id()
        self.assertIn(run_id, self.store.get_prompt_context())

        self.store.finalize_if_active("won")

        self.assertEqual(self.store.get_prompt_context(), "")
        visible_summary = self.store.get_visible_summary()
        self.assertIsNotNone(visible_summary)
        assert visible_summary is not None
        self.assertEqual(visible_summary["source"], "last")
        self.assertEqual(visible_summary["run_id"], run_id)


if __name__ == "__main__":
    unittest.main()
