from __future__ import annotations

import argparse
import json
import shlex
import sys

from . import action_adapter as actions
from .http_client import ApiError, Sts2RawClient
from .state_adapter import normalize_state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sts2",
        description="CLI adapter for controlling the real STS2 game via the local bridge plugin.",
    )
    parser.add_argument("--base-url", default="http://localhost:15526", help="Local bridge API base URL")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout in seconds")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("raw-state", help="Print the raw bridge-plugin JSON state")
    sub.add_parser("state", help="Print the normalized CLI-style state")
    sub.add_parser("continue-game", help="Continue a saved run from the main menu")
    sub.add_parser("abandon-game", help="Abandon the saved run from the main menu")
    sub.add_parser("return-to-main-menu", help="Return to the main menu from an active run")

    p = sub.add_parser("start-game", help="Start a new singleplayer run from the main menu")
    p.add_argument("--character", default="IRONCLAD")
    p.add_argument("--ascension", type=int, default=0)

    p = sub.add_parser("action", help="Send a raw action by name")
    p.add_argument("name", help="Raw bridge-plugin action name")
    p.add_argument("--kv", action="append", default=[], help="Extra payload in key=value form")

    p = sub.add_parser("play-card", help="Play a card by hand index")
    p.add_argument("card_index", type=int)
    p.add_argument("--target")

    p = sub.add_parser("use-potion", help="Use a potion by slot index")
    p.add_argument("slot", type=int)
    p.add_argument("--target")

    sub.add_parser("end-turn", help="End turn")

    p = sub.add_parser("choose-map", help="Choose a map node by normalized index")
    p.add_argument("index", type=int)

    p = sub.add_parser("claim-reward", help="Claim a combat reward by index")
    p.add_argument("index", type=int)

    p = sub.add_parser("pick-card-reward", help="Pick a card reward by index")
    p.add_argument("index", type=int)

    sub.add_parser("skip-card-reward", help="Skip a card reward")
    sub.add_parser("proceed", help="Proceed/leave current room when supported")

    p = sub.add_parser("event", help="Choose an event option by index")
    p.add_argument("index", type=int)
    sub.add_parser("advance-dialogue", help="Advance ancient event dialogue")

    p = sub.add_parser("rest", help="Choose a rest site option by index")
    p.add_argument("index", type=int)

    p = sub.add_parser("shop-buy", help="Purchase a shop item by raw item index")
    p.add_argument("index", type=int)

    p = sub.add_parser("select-card", help="Select a card in an overlay by index")
    p.add_argument("index", type=int)
    sub.add_parser("confirm-selection", help="Confirm the current card selection")
    sub.add_parser("cancel-selection", help="Cancel/skip the current card selection")

    p = sub.add_parser("combat-select-card", help="Select a combat hand card during hand_select")
    p.add_argument("card_index", type=int)
    sub.add_parser("combat-confirm-selection", help="Confirm an in-combat card selection")

    p = sub.add_parser("select-relic", help="Select a relic by index")
    p.add_argument("index", type=int)
    sub.add_parser("skip-relic-selection", help="Skip relic selection")

    p = sub.add_parser("claim-treasure-relic", help="Claim a treasure room relic by index")
    p.add_argument("index", type=int)

    sub.add_parser("repl", help="Start an interactive sts2 shell")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = Sts2RawClient(base_url=args.base_url, timeout=args.timeout)

    try:
        if args.command == "raw-state":
            return _print_json(client.get_state(format="json"))

        if args.command == "state":
            raw = client.get_state(format="json")
            return _print_json(normalize_state(raw))

        if args.command == "continue-game":
            return _post_payload(client, actions.continue_game())

        if args.command == "abandon-game":
            return _post_payload(client, actions.abandon_game())

        if args.command == "return-to-main-menu":
            return _post_payload(client, actions.return_to_main_menu())

        if args.command == "start-game":
            return _post_payload(client, actions.start_new_game(args.character, args.ascension))

        if args.command == "action":
            payload = _parse_kv_pairs(args.kv)
            return _print_json(client.post_action(args.name, **payload))

        if args.command == "play-card":
            return _post_payload(client, actions.play_card(args.card_index, target=args.target))

        if args.command == "use-potion":
            return _post_payload(client, actions.use_potion(args.slot, target=args.target))

        if args.command == "end-turn":
            return _post_payload(client, actions.end_turn())

        if args.command == "choose-map":
            return _post_payload(client, actions.choose_map_node(args.index))

        if args.command == "claim-reward":
            return _post_payload(client, actions.claim_reward(args.index))

        if args.command == "pick-card-reward":
            return _post_payload(client, actions.select_card_reward(args.index))

        if args.command == "skip-card-reward":
            return _post_payload(client, actions.skip_card_reward())

        if args.command == "proceed":
            return _post_payload(client, actions.proceed())

        if args.command == "event":
            return _post_payload(client, actions.choose_event_option(args.index))

        if args.command == "advance-dialogue":
            return _post_payload(client, actions.advance_dialogue())

        if args.command == "rest":
            return _post_payload(client, actions.choose_rest_option(args.index))

        if args.command == "shop-buy":
            return _post_payload(client, actions.shop_purchase(args.index))

        if args.command == "select-card":
            return _post_payload(client, actions.select_card(args.index))

        if args.command == "confirm-selection":
            return _post_payload(client, actions.confirm_selection())

        if args.command == "cancel-selection":
            return _post_payload(client, actions.cancel_selection())

        if args.command == "combat-select-card":
            return _post_payload(client, actions.combat_select_card(args.card_index))

        if args.command == "combat-confirm-selection":
            return _post_payload(client, actions.combat_confirm_selection())

        if args.command == "select-relic":
            return _post_payload(client, actions.select_relic(args.index))

        if args.command == "skip-relic-selection":
            return _post_payload(client, actions.skip_relic_selection())

        if args.command == "claim-treasure-relic":
            return _post_payload(client, actions.claim_treasure_relic(args.index))

        if args.command == "repl":
            return _run_repl(args.base_url, args.timeout)

        parser.error(f"Unhandled command: {args.command}")
        return 2
    except (ApiError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _post_payload(client: Sts2RawClient, payload: dict[str, object]) -> int:
    action = str(payload.pop("action"))
    return _print_json(client.post_action(action, **payload))


def _parse_kv_pairs(entries: list[str]) -> dict[str, object]:
    result: dict[str, object] = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"Expected key=value, got: {entry}")
        key, raw_value = entry.split("=", 1)
        result[key] = _coerce_value(raw_value)
    return result


def _coerce_value(raw: str) -> object:
    if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
        return int(raw)
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    return raw


def _print_json(value: object) -> int:
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def _run_repl(base_url: str, timeout: float) -> int:
    print("STS2CLI REPL")
    print("Type a normal subcommand such as `state` or `play-card 0 --target NIBBIT_0`.")
    print("Type `help` to show command help. Type `exit` or `quit` to leave.")

    while True:
        try:
            line = input("sts2> ").strip()
        except EOFError:
            sys.stdout.write("\n")
            return 0
        except KeyboardInterrupt:
            sys.stdout.write("\n")
            return 0

        if not line:
            continue
        if line in {"exit", "quit"}:
            return 0
        if line == "help":
            build_parser().print_help()
            continue

        argv = ["--base-url", base_url, "--timeout", str(timeout), *shlex.split(line)]
        code = main(argv)
        if code != 0:
            print(f"[exit {code}]", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
