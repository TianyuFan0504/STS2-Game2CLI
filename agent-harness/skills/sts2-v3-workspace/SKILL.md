---
name: sts2-v3-workspace
description: Use the STS2 Memory V3 workspace as a free-form Markdown notebook for gameplay. Use when Codex wants to store, update, or read long-lived notes, plans, observations, heuristics, reminders, experiments, or strategy ideas during or between runs. The workspace root is `memory/global_memory/`. Only `.md` files belong there. Do not impose a fixed schema or template unless the task itself benefits from one.
---

# STS2 V3 Workspace

## Objective

Use `memory/global_memory/` as a persistent free-form Markdown workspace.

The purpose of this skill is not structured indexing. The purpose is to let the gameplay agent freely decide:

- what to remember
- how to organize it
- when to read it
- when to update it

## Workspace Rules

- Treat `memory/global_memory/` as the only V3 workspace root.
- Only create or modify `.md` files inside that root.
- Subdirectories are allowed.
- Do not create a mandatory schema.
- Do not assume any specific filename convention is required.

## When To Use It

Use this skill when any of these are useful:

- keep reusable gameplay notes across runs
- write observations during a live run
- maintain enemy-specific or boss-specific notes
- track open questions or experiments
- keep strategy reminders for a character, relic, or deck pattern
- store free-form thoughts that do not fit V1 or V2 structures

Do not use this skill when:

- current `sts2 state` alone is enough
- V1 short-term summary is enough
- V2 structured archive is better suited for historical lookup

## Query Pattern

Before creating a new note, first inspect what already exists:

```bash
find memory/global_memory -type f -name '*.md' | sort
```

If you need text search:

```bash
rg -n "<query>" memory/global_memory
```

If you need to read one file:

```bash
sed -n '1,220p' memory/global_memory/<path>.md
```

## Write Pattern

You may freely create or update Markdown files under `memory/global_memory/`.

Good examples:

- `memory/global_memory/ironclad.md`
- `memory/global_memory/enemies/jaw-worm.md`
- `memory/global_memory/relics/vajra.md`
- `memory/global_memory/open-questions.md`

Bad examples:

- writing outside `memory/global_memory/`
- creating `.json`, `.txt`, or other non-Markdown files there
- inventing a rigid schema just because one could exist

## Content Guidance

Prefer concise notes that are easy to scan later.

Possible note shapes:

- bullet lists
- short sections
- per-match observations
- small decision logs
- "what seems true" / "what to test next"

Use whatever structure is useful for the task at hand. Do not force uniformity.
