---
name: sts2-game-player
description: Play Slay the Spire 2 autonomously through the local `sts2` CLI bridge. Use when Codex should read `sts2 state`, decide concrete `sts2 ...` commands itself, continue or start runs from the menu, fight combats, choose map nodes and rewards, and keep the game moving without using `sts2 agent-step` or `sts2 agent-run`.
metadata:
  short-description: Play STS2 through the local sts2 CLI bridge
---

# STS2 Game Player

## Objective
Operate the real Slay the Spire 2 game through the local `sts2` CLI bridge as a persistent command-line game agent.

Each invocation should make forward progress, not just inspect state.

## Hard Rules

- Always start from `sts2 state`.
- Never use `sts2 agent-step` or `sts2 agent-run`.
- Generate explicit `sts2 ...` commands yourself.
- Re-read `sts2 state` after every meaningful action, especially during combat.
- Do not modify source code while playing the game.
- If the bridge is unavailable, stop and report that the game or bridge plugin is not ready.
- If the game is at the main menu, prefer `sts2 continue-game`; if that is unavailable, use `sts2 start-game --character IRONCLAD --ascension 0`.
- If a run has ended and the menu is the only available state, immediately start a new Ironclad A0 run and keep going unless the user asked to stop.

## Session Pattern

1. Run `sts2 state`.
2. Identify the normalized `decision`.
3. Choose the next concrete `sts2 ...` command.
4. Execute it.
5. Re-check state.
6. Continue until you reach a stable pause point for the current invocation.

Stable pause points:

- A new decision screen after making progress.
- The main menu after a run ends.
- An unrecoverable bridge or command error.

If a reward screen has obvious follow-up actions left, do not stop too early. Claim obvious gold, potions, relics, and card rewards before pausing.

## Decision Routing

Read `references/sts2-cli-surface.md` for the command/state map.

- `menu`: continue the existing run if possible; otherwise start a new Ironclad A0 run.
- `combat_play`: play cards manually with `sts2 play-card ...`, use `sts2 use-potion ...` only when justified, and `sts2 end-turn` only when no useful play remains.
- `hand_select`: use `sts2 combat-select-card` and `sts2 combat-confirm-selection`.
- `map_select`: choose the safest route that still advances the run.
- `game_over`: call `sts2 return-to-main-menu` until the state becomes `menu`, then start or continue the next run.
- `combat_rewards`: claim high-value rewards, then `sts2 proceed` if the room is done.
- `card_reward`: pick a card only when it clearly improves the deck; otherwise `sts2 skip-card-reward`.
- `event_choice`: use `sts2 advance-dialogue` for dialogue-only ancient-event screens, otherwise `sts2 event <index>`.
- `rest_site`: rest when HP is low or survival is in doubt; otherwise prefer upgrades/value.
- `shop`: buy only strong upgrades, premium relics, premium cards, or efficient card removal.
- `card_select`: use `sts2 select-card`, `sts2 confirm-selection`, and `sts2 cancel-selection`.
- `relic_select`: choose the best relic with `sts2 select-relic`, or skip only when the state explicitly supports it.
- `treasure`: claim the best relic first, then proceed when available.

## Combat Heuristics

Read `references/play-heuristics.md` before making extended combat decisions.

- Take lethal immediately when it is available.
- Prefer lines that reduce expected HP loss.
- If incoming damage can be fully or almost fully blocked at reasonable cost, value that highly.
- Use permanent buffs, strength, vulnerable, weak, and premium debuffs early in longer fights.
- Re-read state after each card because energy, hand contents, and indices change.
- When several cards are equivalent, prefer the rightmost playable card to reduce hand-index drift.
- Use potions for survival, lethal, elites, bosses, or to avoid meaningful HP loss; do not spend them casually.
- End turn only after checking that no higher-value play remains.

## Reward and Path Heuristics

- Prefer rewards that strengthen consistency: efficient block, draw, strength scaling, premium attacks, premium debuffs, and high-value relics.
- Skip weak or deck-cluttering card rewards when none clearly help.
- Prefer safer map paths by default.
- Avoid early elites unless HP, deck quality, and relic support justify the risk.
- Visit campfires when HP is becoming a real constraint.
- At shops, card removal is often strong when it competes favorably with low-impact purchases.
- In events, avoid curses or large HP payments unless the payoff is clearly strong.

## Logging

If `STS2CLI_SESSION_DIR` is set, append concise progress notes to:

- `$STS2CLI_SESSION_DIR/gameplay_journal.md`

Each update should capture:

- current floor / act
- previous and new decision state
- important commands executed
- HP change, rewards, and notable picks

## Output Contract

Keep the final response short.

End with exactly one final line:

`RESULT: <short summary>`
