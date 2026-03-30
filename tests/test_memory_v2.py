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
        self.artifact_root = Path(self.tempdir.name) / "artifacts"
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_iteration_artifacts(self, iteration: int, mode: str = "single") -> None:
        raw_path = self.artifact_root / f"iter_{iteration:04d}.raw.jsonl"
        text_path = self.artifact_root / f"iter_{iteration:04d}.log"
        raw_path.write_text('{"kind":"mock"}\n', encoding="utf-8")
        text_path.write_text("[mock] iteration\n", encoding="utf-8")
        self.store.write_runtime_prompt(f"Iteration {iteration:04d}", iteration=iteration, mode=mode)
        self.store.record_iteration_artifacts(iteration, raw_path=raw_path, text_path=text_path)

    def test_finalized_run_generates_turns_rewards_battles_and_archive_index(self) -> None:
        map_state = build_state(
            "map_select",
            state_type="decision",
            visited=[{"col": 0, "row": 0, "type": "start"}],
            current_position={"col": 0, "row": 0, "type": "start"},
            choices=[],
        )
        combat_state = build_state(
            "combat_play",
            state_type="decision",
            floor=2,
            hp=80,
            max_hp=80,
            gold=99,
            hand=[],
            room_type="monster",
            enemies=[{"entity_id": "jaw_worm_0", "name": "Jaw Worm", "hp": 40, "max_hp": 40}],
        )
        combat_rewards_state = build_state(
            "combat_rewards",
            state_type="decision",
            floor=2,
            hp=72,
            max_hp=80,
            gold=120,
            items=[{"index": 0, "type": "gold", "gold_amount": 21}],
            can_proceed=True,
        )
        card_reward_state = build_state(
            "card_reward",
            state_type="decision",
            floor=2,
            hp=72,
            max_hp=80,
            gold=120,
            cards=[
                {"index": 0, "id": "pommel_strike", "name": "Pommel Strike"},
                {"index": 1, "id": "shrug_it_off", "name": "Shrug It Off"},
            ],
            can_skip=True,
        )
        shop_state = build_state(
            "shop",
            state_type="decision",
            floor=3,
            hp=72,
            max_hp=80,
            gold=120,
            items=[
                {"index": 0, "category": "card", "card_id": "spot_weakness", "card_name": "Spot Weakness", "cost": 54},
                {"index": 1, "category": "relic", "relic_id": "vajra", "relic_name": "Vajra", "cost": 150},
                {"index": 2, "category": "card_removal", "cost": 75},
            ],
            cards=[{"index": 0, "card_id": "spot_weakness", "card_name": "Spot Weakness", "cost": 54}],
            relics=[{"index": 1, "relic_id": "vajra", "relic_name": "Vajra", "cost": 150}],
            card_removal={"index": 2, "category": "card_removal", "cost": 75},
            can_proceed=True,
        )
        shop_after_card_state = build_state(
            "shop",
            state_type="decision",
            floor=3,
            hp=72,
            max_hp=80,
            gold=66,
            items=[
                {"index": 1, "category": "relic", "relic_id": "vajra", "relic_name": "Vajra", "cost": 150},
                {"index": 2, "category": "card_removal", "cost": 75},
            ],
            cards=[],
            relics=[{"index": 1, "relic_id": "vajra", "relic_name": "Vajra", "cost": 150}],
            card_removal={"index": 2, "category": "card_removal", "cost": 75},
            can_proceed=True,
        )
        treasure_state = build_state(
            "treasure",
            state_type="decision",
            floor=4,
            hp=72,
            max_hp=80,
            gold=66,
            relics=[{"index": 0, "id": "preserved_insect", "name": "Preserved Insect"}],
            can_proceed=False,
        )
        upgrade_state = build_state(
            "card_select",
            state_type="decision",
            floor=4,
            hp=72,
            max_hp=80,
            gold=66,
            screen_type="upgrade",
            prompt="Choose a card to upgrade.",
            cards=[{"index": 0, "id": "bash", "name": "Bash", "is_upgraded": False}],
            can_confirm=True,
            can_cancel=True,
        )
        next_map_state = build_state(
            "map_select",
            state_type="decision",
            floor=5,
            hp=72,
            max_hp=80,
            gold=66,
            visited=[
                {"col": 0, "row": 0, "type": "start"},
                {"col": 1, "row": 0, "type": "monster"},
                {"col": 2, "row": 0, "type": "shop"},
                {"col": 2, "row": 1, "type": "treasure"},
            ],
            current_position={"col": 2, "row": 1, "type": "treasure"},
            choices=[],
        )

        self.store.record_state(map_state, source="iteration_start")
        run_id = self.store.get_active_run_info()["run_id"]

        self.store.prepare_turn(1, mode="single", state=map_state)
        self.store.record_command("choose-map 0", result="ok", source="agent")
        self._write_iteration_artifacts(1)
        self.store.record_state(combat_state, source="iteration_end")

        self.store.prepare_turn(2, mode="single", state=combat_state)
        self.store.record_command("end-turn", result="ok", source="agent")
        self._write_iteration_artifacts(2)
        self.store.record_state(combat_rewards_state, source="iteration_end")

        self.store.prepare_turn(3, mode="single", state=combat_rewards_state)
        self.store.record_command("claim-reward 0", result="ok", source="agent")
        self._write_iteration_artifacts(3)
        self.store.record_state(card_reward_state, source="iteration_end")

        self.store.prepare_turn(4, mode="single", state=card_reward_state)
        self.store.record_command("pick-card-reward 1", result="ok", source="agent")
        self._write_iteration_artifacts(4)
        self.store.record_state(shop_state, source="iteration_end")

        self.store.prepare_turn(5, mode="single", state=shop_state)
        self.store.record_command("shop-buy 0", result="ok", source="agent")
        self._write_iteration_artifacts(5)
        self.store.record_state(shop_after_card_state, source="iteration_end")

        self.store.prepare_turn(6, mode="single", state=shop_after_card_state)
        self.store.record_command("shop-buy 1", result="ok", source="agent")
        self._write_iteration_artifacts(6)
        self.store.record_state(treasure_state, source="iteration_end")

        self.store.prepare_turn(7, mode="single", state=treasure_state)
        self.store.record_command("claim-treasure-relic 0", result="ok", source="agent")
        self._write_iteration_artifacts(7)
        self.store.record_state(upgrade_state, source="iteration_end")

        self.store.prepare_turn(8, mode="single", state=upgrade_state)
        self.store.record_command("select-card 0", result="ok", source="agent")
        self.store.record_command("confirm-selection", result="ok", source="agent")
        self._write_iteration_artifacts(8)
        self.store.record_state(next_map_state, source="iteration_end")

        self.store.finalize_if_active("won")

        run_dir = self.root / "runs" / run_id
        turns_dir = run_dir / "turns"
        rewards_dir = run_dir / "rewards"
        battles_dir = run_dir / "battles"

        turn_files = sorted(turns_dir.glob("turn_*.json"))
        self.assertEqual(len(turn_files), 8)
        first_turn = json.loads(turn_files[0].read_text(encoding="utf-8"))
        last_turn = json.loads(turn_files[-1].read_text(encoding="utf-8"))
        self.assertEqual(first_turn["decision_before"], "map_select")
        self.assertEqual(first_turn["decision_after"], "combat_play")
        self.assertEqual(first_turn["commands"][0]["command"], "choose-map 0")
        self.assertEqual(first_turn["state_before_details"]["decision"], "map_select")
        self.assertEqual(last_turn["decision_before"], "card_select")
        self.assertEqual(last_turn["decision_after"], "map_select")
        self.assertEqual(last_turn["commands"][0]["command"], "select-card 0")

        reward_files = sorted(rewards_dir.glob("reward_*.json"))
        self.assertEqual(len(reward_files), 6)
        reward_sources = [json.loads(path.read_text(encoding="utf-8"))["source"] for path in reward_files]
        self.assertEqual(reward_sources, ["combat_rewards", "card_reward", "shop", "shop", "treasure", "card_select"])
        first_shop_reward = json.loads(reward_files[2].read_text(encoding="utf-8"))
        self.assertEqual(first_shop_reward["chosen"]["card_name"], "Spot Weakness")
        self.assertEqual(first_shop_reward["chosen_command"], "shop-buy 0")

        battle_files = sorted(battles_dir.glob("battle_*.json"))
        self.assertEqual(len(battle_files), 1)
        battle = json.loads(battle_files[0].read_text(encoding="utf-8"))
        self.assertEqual(battle["result"], "won")
        self.assertEqual(battle["floor"], 2)
        self.assertEqual(battle["turn_count"], 2)
        self.assertEqual(battle["hp_before"], 80)
        self.assertEqual(battle["hp_after"], 72)
        self.assertEqual(battle["enemy_names"], ["Jaw Worm"])
        self.assertEqual(battle["enemy_signature"], "jaw_worm_0")

        route_timeline = json.loads((run_dir / "derived" / "route_timeline.json").read_text(encoding="utf-8"))
        self.assertEqual(route_timeline["run_id"], run_id)
        self.assertEqual(route_timeline["entries"][-1]["type"], "treasure")

        resource_timeline = json.loads((run_dir / "derived" / "resource_timeline.json").read_text(encoding="utf-8"))
        self.assertEqual(resource_timeline["turn_count"], 8)
        event_types = [entry["event_type"] for entry in resource_timeline["entries"]]
        self.assertIn("hp_change", event_types)
        self.assertIn("gold_change", event_types)
        self.assertIn("floor_change", event_types)

        deck_timeline = json.loads((run_dir / "derived" / "deck_timeline.json").read_text(encoding="utf-8"))
        card_ops = [(entry["card_name"], entry["op"]) for entry in deck_timeline["events"]]
        self.assertIn(("Shrug It Off", "add"), card_ops)
        self.assertIn(("Spot Weakness", "add"), card_ops)
        self.assertIn(("Bash", "upgrade"), card_ops)

        relic_timeline = json.loads((run_dir / "derived" / "relic_timeline.json").read_text(encoding="utf-8"))
        relic_names = [entry["relic_name"] for entry in relic_timeline["events"]]
        self.assertEqual(relic_names, ["Vajra", "Preserved Insect"])

        run_tags = json.loads((run_dir / "derived" / "run_tags.json").read_text(encoding="utf-8"))
        tags = {(tag["tag_type"], tag["tag_value"]) for tag in run_tags["tags"]}
        self.assertIn(("character", "IRONCLAD"), tags)
        self.assertIn(("result", "won"), tags)
        self.assertIn(("battle_count", "1"), tags)
        self.assertIn(("reward_count", "6"), tags)
        self.assertIn(("card_event_count", "3"), tags)
        self.assertIn(("relic_event_count", "2"), tags)

        archive_runs = self.store.v2.find_runs(character="IRONCLAD")
        self.assertEqual(len(archive_runs), 1)
        self.assertEqual(archive_runs[0]["run_id"], run_id)
        self.assertEqual(archive_runs[0]["result"], "won")

        tagged_runs = self.store.v2.find_runs_by_tag("result", "won")
        self.assertEqual(len(tagged_runs), 1)
        self.assertEqual(tagged_runs[0]["run_id"], run_id)

        indexed_battles = self.store.v2.find_battles(run_id=run_id)
        self.assertEqual(len(indexed_battles), 1)
        self.assertEqual(indexed_battles[0]["result"], "won")

        card_events = self.store.v2.find_card_events(card_name="Spot Weakness")
        self.assertEqual(len(card_events), 1)
        self.assertEqual(card_events[0]["op"], "add")

        relic_events = self.store.v2.find_relic_events(relic_name="Vajra")
        self.assertEqual(len(relic_events), 1)
        self.assertEqual(relic_events[0]["op"], "add")


if __name__ == "__main__":
    unittest.main()
