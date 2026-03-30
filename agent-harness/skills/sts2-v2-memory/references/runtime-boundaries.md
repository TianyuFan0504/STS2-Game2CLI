# Runtime Boundaries

## V1 vs V2

Use this rule:

- **V1** = current-run, online, prompt-facing
- **V2** = finalized-run, offline, archive-facing

## What V1 owns

V1 is responsible for:

- active run lifecycle
- `session.json`
- `state_snapshot.json`
- `ledger.jsonl`
- `events.jsonl`
- `agent_events.jsonl`
- `runtime_prompt.md`
- `memory/summary.md`

When the question is about the current in-progress run, prefer V1 and `sts2 state`.

## What V2 owns

V2 is responsible for:

- `turns/`
- `battles/`
- `rewards/`
- `derived/*.json`
- `memory/archive/index.sqlite`

V2 materialization happens on run finalize, not on every turn.

## Current practical limits

- Active-run SQLite data may be stale or absent.
- `turns/` are reconstructed from V1 ledger plus `turn_started` markers.
- `rewards/` are useful but not full replay fidelity.
- `battles/` are useful summaries but enemy/room detail is still partial.
- `deck_timeline.json` and `relic_timeline.json` are delta extraction, not perfect full-state replay.

## Recommended evidence order

For current-run questions:

1. `sts2 state`
2. current run `memory/summary.md`
3. other V1 files if needed

For completed-run questions:

1. SQLite to find candidate runs
2. `derived/*.json` to verify
3. `turns/`, `battles/`, `rewards/` for deeper detail

For cross-run claims:

1. SQLite for filtering
2. spot-check at least one matching run directory before making detailed causal claims
