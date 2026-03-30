Hard runtime rules:

- Do not modify source code, settings files, or project files while playing, except Markdown files under `memory/globao_memory/`.
- Do not run `git`, `npm`, `pnpm`, `brew`, `python`, or other development commands.
- Use shell commands mainly for `sts2 ...` and lightweight diagnostics such as `pwd` or `ls` when necessary.
- Generate explicit `sts2 ...` commands yourself.
- During a single print-mode invocation, keep making forward progress until you reach a stable pause point after resolving obvious follow-up actions.
- If blocked by bridge connectivity, missing game state, or missing provider auth, say so clearly and stop.
