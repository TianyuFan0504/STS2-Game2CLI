# Current Memory State

这份文档只描述**当前仓库已经实际落地的 memory 行为**，不重复设计稿里的未来目标。

## 1. 总体结构

当前 memory 根目录结构是：

```text
memory/
├── archive/
│   └── index.sqlite
├── latest -> runs/<run_id>
└── runs/
    └── <run_id>/
        ├── battles/
        ├── data/
        │   ├── agent_events.jsonl
        │   ├── events.jsonl
        │   ├── iterations/
        │   │   └── <iteration>/
        │   │       ├── pi.log
        │   │       └── pi.raw.jsonl
        │   ├── ledger.jsonl
        │   ├── runtime_prompt.md
        │   ├── session.json
        │   └── state_snapshot.json
        ├── derived/
        │   ├── deck_timeline.json
        │   ├── relic_timeline.json
        │   ├── resource_timeline.json
        │   ├── route_timeline.json
        │   └── run_tags.json
        ├── memory/
        │   └── summary.md
        ├── rewards/
        └── turns/
```

说明：

- `memory/runs/<run_id>/...` 是单局事实数据
- `memory/archive/index.sqlite` 是跨局索引
- `memory/latest` 指向最近一个 run 目录

## 2. V1 当前行为

### 2.1 run 生命周期

当前 run 的触发规则是：

- 第一次进入非 `menu` 状态时创建 run
- run 结束时写 `run_ended`
- 如果只是停止 agent，而游戏还在这一局里，run 不会被错误结束
- 从主菜单 `abandon-game` 后回到不可继续的 `menu`，run 会被判为 `abandoned`

当前 `session.json` 已经会记录：

- `run_id`
- `status`
- `result`
- `character`
- `ascension`
- `started_at`
- `ended_at`
- `latest_act`
- `latest_floor`
- `latest_seq_id`
- `latest_event_id`
- `latest_agent_seq_id`
- `latest_decision`
- `latest_state_type`
- `last_hp`
- `last_max_hp`
- `last_gold`
- `last_command`
- `last_command_source`
- `last_command_at`
- `last_state_source`

### 2.2 prompt 注入

当前只会把下面两类上下文给 agent：

- 当前 `sts2 state`
- 当前活动 run 的 `memory/summary.md`

不会注入：

- 历史 run
- `events.jsonl`
- `agent_events.jsonl`
- SQLite 长期索引

如果 run 已结束，前端仍可展示上一个 run 的 summary，但不会再把它注入新一轮 prompt。

## 3. V2 当前行为

当前 V2 是 **Phase-1 落地**，目标是先把最小可用的单局派生物和跨局索引建立起来。

### 3.1 何时生成

当前是在 run finalize 时生成 V2 数据：

1. 先完成 V1 的 `session.json / summary.md / state_snapshot.json / events.jsonl`
2. 再生成单局派生目录
3. 最后写 `memory/archive/index.sqlite`

### 3.2 `turns/`

当前已经会为每轮 agent iteration 写 turn 摘要：

- turn 边界来自 `ledger.jsonl` 里的 `turn_started` artifact
- 每个 turn 文件会包含：
  - `turn_id`
  - `iteration`
  - `started_at`
  - `ended_at`
  - `mode`
  - `decision_before`
  - `decision_after`
  - `state_before`
  - `state_after`
  - `commands`
  - `assistant_output`
  - `summary`
  - `artifacts`

当前 turn 重建主要基于：

- `turn_started`
- `sts2_command`
- `runtime_prompt`
- `iteration_artifacts`
- 事件流里的状态变化

### 3.3 `battles/`

当前 battle 摘要是 Phase-1 版本：

- 通过连续 combat turns 聚合得到
- 每个 battle 文件当前包含：
  - `battle_id`
  - `run_id`
  - `act`
  - `floor`
  - `hp_before`
  - `hp_after`
  - `turn_count`
  - `result`
  - `turn_ids`
  - `commands`

当前限制：

- 还没有稳定提取 `enemy_names`
- `enemy_signature` 还未补全
- `room_type` 还没有完整结构化

### 3.4 `rewards/`

当前 reward 摘要也是 Phase-1 版本：

- 会从 reward 相关 decision turn 里抽取
- 当前覆盖：
  - `combat_rewards`
  - `card_reward`
  - `event_choice`
  - `rest_site`
  - `shop`
  - `card_select`
  - `relic_select`
  - `treasure`

每个 reward 文件当前包含：

- `reward_id`
- `run_id`
- `turn_id`
- `act`
- `floor`
- `source`
- `chosen`
- `skipped`
- `commands`
- `decision_after`
- `notes`

当前限制：

- `options` 还没有完整回放
- 还没有卡牌 / 遗物 / 药水级别的标准化结构

目前已经会在 reward 文件里写：

- `options`
- `chosen`
- `chosen_command`

但它仍然是基于当前 turn `state_before` 的结构化提取，不是完整的 replay 层。

### 3.5 `derived/`

当前已经会生成：

- `deck_timeline.json`
- `relic_timeline.json`
- `route_timeline.json`
- `resource_timeline.json`
- `run_tags.json`

用途分别是：

- `route_timeline.json`
  - 保存路线推进结果
- `deck_timeline.json`
  - 保存当前已能识别出的卡牌 delta 事件
- `relic_timeline.json`
  - 保存当前已能识别出的遗物 delta 事件
- `resource_timeline.json`
  - 保存 HP / Gold / Floor / Act 的变化时间线
- `run_tags.json`
  - 保存当前可检索标签

## 4. SQLite 当前状态

当前 `memory/archive/index.sqlite` 已经包含这些表：

- `runs`
- `run_cards`
- `run_relics`
- `run_tags`
- `run_battles`

当前已经支持的最小检索能力：

- 按 `character` / `result` 查 runs
- 按 `card_id` / `card_name` 查 card events
- 按 `relic_id` / `relic_name` 查 relic events
- 按 tag 查 runs
- 按 `run_id` / `result` 查 battles
- 按组合条件搜索 runs
- 读取单个 run 的 replay/detail 视图
- 基础 archive stats

前端当前已经有：

- replay / search API
- 基础 archive stats API
- 控制台里的 archive search / replay / stats 面板

当前还没有：

- 更深入的聚合统计

## 5. 当前限制

当前 memory 系统已经能支撑：

- 单局短期记忆
- 当前 run summary 注入
- 局结束后的 turn / reward / battle / derived 归档
- 最小跨局索引
- 卡牌 / 遗物 delta 时间线与索引
- `victory.md` / `postmortem.md`
- 前端 replay / search / stats 面板

但还没有完全做到：

- 更细的 battle enemy 结构
- 完整 reward replay 与多阶段选择回放
- 跨局 lessons 抽取
