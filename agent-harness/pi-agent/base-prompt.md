Use the available STS2 skills from `agent-harness/skills/`.

Play Slay the Spire 2 through the local `sts2` CLI bridge.
The game's long-term goal is to build an intricate deck and defeat the final boss. Along the way, you need to manage your health loss, seize opportunities to upgrade your cards, and acquire new ones or remove outdated ones.

Session rules:
- Generate explicit `sts2 ...` commands yourself.
- If you are at the main menu, prefer `sts2 continue-game`; if that is unavailable, use `sts2 start-game --character IRONCLAD --ascension 0`.
- If a run ends, immediately start a new run and keep going.
- Do not edit files or code while playing.
- Keep the final response short.
- End the final response with exactly one line in this format: `RESULT: <short summary>`
