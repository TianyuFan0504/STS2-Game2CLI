# Query Recipes

Use these commands from the repository root.

## Inspect schema

```bash
sqlite3 memory/archive/index.sqlite ".schema"
```

## List recent runs

```bash
sqlite3 -header -column memory/archive/index.sqlite \
  "SELECT run_id, ended_at, character, ascension, result, final_act, final_floor
   FROM runs
   ORDER BY ended_at DESC
   LIMIT 20;"
```

## List recent wins for a character

```bash
sqlite3 -header -column memory/archive/index.sqlite \
  "SELECT run_id, ended_at, final_floor
   FROM runs
   WHERE character = 'IRONCLAD' AND result = 'won'
   ORDER BY ended_at DESC
   LIMIT 20;"
```

## Find runs by tag

```bash
sqlite3 -header -column memory/archive/index.sqlite \
  "SELECT runs.run_id, runs.character, runs.result, run_tags.tag_type, run_tags.tag_value
   FROM run_tags
   JOIN runs ON runs.run_id = run_tags.run_id
   WHERE run_tags.tag_type = 'boss'
   ORDER BY runs.ended_at DESC
   LIMIT 20;"
```

## Find card events

```bash
sqlite3 -header -column memory/archive/index.sqlite \
  "SELECT run_id, card_name, op, floor, turn_id, source
   FROM run_cards
   WHERE card_name = 'Shrug It Off'
   ORDER BY run_id, floor, turn_id;"
```

## Find relic events

```bash
sqlite3 -header -column memory/archive/index.sqlite \
  "SELECT run_id, relic_name, op, floor, turn_id, source
   FROM run_relics
   WHERE relic_name = 'Vajra'
   ORDER BY run_id, floor, turn_id;"
```

## Find battles by outcome or enemy signature

```bash
sqlite3 -header -column memory/archive/index.sqlite \
  "SELECT run_id, battle_id, floor, enemy_signature, result
   FROM run_battles
   WHERE result = 'lost'
   ORDER BY run_id, battle_id;"
```

```bash
sqlite3 -header -column memory/archive/index.sqlite \
  "SELECT run_id, battle_id, floor, enemy_signature, result
   FROM run_battles
   WHERE enemy_signature LIKE '%jaw_worm%'
   ORDER BY run_id, battle_id;"
```

## Inspect one run directory

```bash
find memory/runs/<run_id> -maxdepth 2 -type f | sort
```

## Read derived summaries for one run

```bash
sed -n '1,220p' memory/runs/<run_id>/derived/run_tags.json
sed -n '1,220p' memory/runs/<run_id>/derived/deck_timeline.json
sed -n '1,220p' memory/runs/<run_id>/derived/relic_timeline.json
sed -n '1,220p' memory/runs/<run_id>/derived/resource_timeline.json
```

## Inspect recent turns for one run

```bash
find memory/runs/<run_id>/turns -type f | sort | tail -5
sed -n '1,220p' memory/runs/<run_id>/turns/turn_0001.json
```

## Inspect reward and battle files

```bash
find memory/runs/<run_id>/rewards -type f | sort
find memory/runs/<run_id>/battles -type f | sort
```
