# STS2 CLI Surface

## Core Read Command

- `sts2 state`
  - Returns normalized JSON with a `decision` field.

## Main Menu

- `sts2 continue-game`
- `sts2 start-game --character IRONCLAD --ascension 0`
- `sts2 abandon-game`
- `sts2 return-to-main-menu`

## Combat

- `sts2 play-card <card_index> [--target <enemy_id>]`
- `sts2 use-potion <slot> [--target <enemy_id>]`
- `sts2 end-turn`

## Map and Room Flow

- `sts2 choose-map <index>`
- `sts2 proceed`

## Rewards

- `sts2 claim-reward <index>`
- `sts2 pick-card-reward <index>`
- `sts2 skip-card-reward`
- `sts2 claim-treasure-relic <index>`
- `sts2 select-relic <index>`
- `sts2 skip-relic-selection`

## Events and Rest Sites

- `sts2 event <index>`
- `sts2 advance-dialogue`
- `sts2 rest <index>`

## Shop

- `sts2 shop-buy <index>`

## Card Selection Overlays

- `sts2 select-card <index>`
- `sts2 confirm-selection`
- `sts2 cancel-selection`
- `sts2 combat-select-card <card_index>`
- `sts2 combat-confirm-selection`

## Normalized Decision Names

- `menu`
- `combat_play`
- `hand_select`
- `map_select`
- `combat_rewards`
- `card_reward`
- `event_choice`
- `rest_site`
- `shop`
- `card_select`
- `relic_select`
- `treasure`
- `overlay`
- `unknown`
