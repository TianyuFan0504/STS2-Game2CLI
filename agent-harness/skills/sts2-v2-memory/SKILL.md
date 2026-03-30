---
name: sts2-v2-memory
description: Query STS2 Memory V2 as a library of experience from previous runs so the gameplay agent can make better decisions. Use when Codex should look up past battles, rewards, card and relic outcomes, inspect completed-run `turns/`, `battles/`, `rewards/`, or `derived/` files, or query `memory/archive/index.sqlite` for cross-run evidence before deciding what to do next.
---

# STS2 V2 Memory

## Overview

Use this skill as a searchable archive of experience from previous runs.

The goal is not just to inspect files. The goal is to let the gameplay agent look up what happened in earlier runs and use that evidence to make better decisions in the current one.

- historical runs
- cross-run patterns
- card / relic / battle history
- explaining what Memory V2 currently stores
- checking whether V2 materialized a completed run correctly

## Source Selection

Choose the source of truth before querying:

1. **Completed run, detailed inspection**
   Read files under `memory/runs/<run_id>/`.
   Prefer:
   - `turns/*.json` for per-iteration reasoning and commands
   - `battles/*.json` for battle summaries
   - `rewards/*.json` for reward decisions
   - `derived/*.json` for route / resource / card / relic deltas

3. **Cross-run filtering or lookup**
   Query `memory/archive/index.sqlite`.
   Use SQLite first to find candidate runs, then inspect the matching run folders for detail.

## Workflow

### 1. Confirm archive availability

Check that Memory V2 data exists:

```bash
find memory -maxdepth 3 \( -name index.sqlite -o -name summary.md \) | sort
```

If `memory/archive/index.sqlite` is missing, fall back to scanning `memory/runs/` directly.

### 2. Decide whether the run is active or finalized

For a currently running game, V2 may be stale because materialization happens on run finalize.

If the user asks about the current in-progress run:

- prefer `sts2 state`
- prefer current `memory/runs/<run_id>/memory/summary.md`
- only use V2 artifacts as historical context

### 3. For a specific run, inspect files before making claims

After locating a `run_id`, inspect the run directory:

```bash
find memory/runs/<run_id> -maxdepth 2 -type f | sort
```

Suggested read order:

1. `derived/run_tags.json`
2. `derived/deck_timeline.json`
3. `derived/relic_timeline.json`
4. `battles/*.json`
5. `rewards/*.json`
6. `turns/*.json`

Use `turns/*.json` when you need agent-step chronology, not just final outcomes.

### 4. For cross-run work, use SQLite as the index layer

Use `sqlite3` against:

```text
memory/archive/index.sqlite
```

Current useful tables are:

- `runs`
- `run_cards`
- `run_relics`
- `run_tags`
- `run_battles`

Read [references/query-recipes.md](references/query-recipes.md) for ready-to-use queries.

### 5. Always state current limitations when relevant

Current V2 is useful but not complete. When it matters to the answer, mention:

- active runs are not guaranteed to be in SQLite yet
- reward replay is still partial
- battle enemy / room structure is not fully complete
- card / relic timelines are delta extraction, not a perfect replay of every deck state

Read [references/runtime-boundaries.md](references/runtime-boundaries.md) when you need the exact boundary between V1 and V2.

## Query Strategy

Use this order for reliable answers:

1. Use SQLite to narrow the search space
2. Use run-level JSON files to verify details
3. Prefer file evidence over inference when they disagree

Examples:

- "How many Ironclad wins are recorded?"
  First query `runs`, then summarize.

- "When did we gain Vajra?"
  First query `run_relics`, then inspect the corresponding run's `rewards/` or `turns/`.

- "Why did this run lose HP so quickly?"
  Inspect `resource_timeline.json`, `battles/*.json`, then relevant `turns/*.json`.

## Runtime Constraints

When used inside the gameplay runtime, avoid development-style commands and prefer lightweight shell access:

- `sqlite3`
- `find`
- `sed`
- `rg`
- `ls`

If you are outside the gameplay runtime, you may still prefer shell-based inspection because the data is already structured for that.

## Output Guidance

When answering from V2 memory:

- distinguish indexed facts from inference
- mention whether the answer came from SQLite or run files
- if the question is about an active run, state that V2 may lag until finalize
