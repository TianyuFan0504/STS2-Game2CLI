# Memory V2

## 1. 目标

V2 的目标是在 V1 单局目录的基础上，增加**跨局索引和经验聚合**能力。

V2 解决的问题：

- 不只是“这一把发生了什么”
- 而是“很多把里有哪些可复用规律”
- 支持按角色、Boss、卡牌、遗物、死亡原因等维度检索历史

V2 不追求：

- 自动策略学习闭环
- embedding / 向量检索
- 多用户共享服务化

## 2. 前提

V2 依赖 V1 已经成立：

- 每一局都有唯一 `run_id`
- 每一局都有独立目录 `memory/runs/<run_id>/`
- 已经有：
  - `session.json`
  - `summary.md`
  - `state_snapshot.json`
  - `events.jsonl`

没有 V1，就不要先做 V2。

## 3. V2 范围

### 3.1 必做

- 增加单局派生目录
  - `turns/`
  - `battles/`
  - `rewards/`
  - `derived/`
- 增加长期索引
  - `memory/archive/index.sqlite`
- 支持跨局检索
- 支持局结束后生成结构化聚合数据

### 3.2 不做

- 自动 lesson 生成
- 自动策略修正
- embedding 检索
- 云端数据库

### 3.3 当前实现状态

当前仓库已经开始落地 V2 的第一阶段：

- 局结束后会生成 `turns/`、`battles/`、`rewards/`、`derived/`
- `derived/` 当前会先写：
  - `deck_timeline.json`
  - `relic_timeline.json`
  - `route_timeline.json`
  - `resource_timeline.json`
  - `run_tags.json`
- `memory/archive/index.sqlite` 当前已包含：
  - `runs`
  - `run_cards`
  - `run_relics`
  - `run_tags`
  - `run_battles`
- 局结束后当前还会生成：
  - `victory.md`
  - `postmortem.md`
- 前端当前已经接入：
  - replay / search API
  - 基础 archive stats API

当前限制：

- `turns/` 主要基于 V1 ledger 和 turn markers 重建
- `battles/` / `rewards/` 目前是 Phase-1 摘要，字段还不完整
- 更深入的聚合统计和 lessons 仍未完成

## 4. 目录结构

V2 目录建议：

```text
memory/
├── runs/
│   └── <run_id>/
│       ├── session.json
│       ├── summary.md
│       ├── state_snapshot.json
│       ├── events.jsonl
│       ├── turns/
│       ├── battles/
│       ├── rewards/
│       └── derived/
├── archive/
│   └── index.sqlite
└── latest
```

## 5. 单局派生数据

### 5.1 `turns/`

按 agent 决策轮存摘要。

用途：

- 回看 agent 每轮输入/输出
- 为 prompt 提供更自然的短期历史切片

### 5.2 `battles/`

按战斗存独立摘要。

建议字段：

- `battle_id`
- `run_id`
- `act`
- `floor`
- `room_type`
- `enemy_names`
- `hp_before`
- `hp_after`
- `potions_used`
- `result`
- `notes`

### 5.3 `rewards/`

记录奖励选择。

建议字段：

- `floor`
- `reward_type`
- `options`
- `chosen`
- `skipped`

### 5.4 `derived/`

保存单局聚合结果。

建议文件：

- `deck_timeline.json`
- `route_timeline.json`
- `resource_timeline.json`
- `run_tags.json`

这些文件用于降低后续长期索引构建成本。

## 6. 长期索引层

### 6.1 存储选择

V2 采用：

- **文件系统**存单局真实数据
- **SQLite**存跨局索引

即：

- `memory/runs/<run_id>/...` 是主数据
- `memory/archive/index.sqlite` 是检索层

## 6.2 索引表

### `runs`

保存每局概要。

建议字段：

- `run_id`
- `session_uuid`
- `started_at`
- `ended_at`
- `character`
- `ascension`
- `seed`
- `result`
- `final_act`
- `final_floor`
- `death_enemy`
- `boss`
- `final_hp`
- `final_gold`
- `summary_path`
- `events_path`

### `run_cards`

记录卡牌变化和最终签名。

建议字段：

- `run_id`
- `card_id`
- `card_name`
- `op`
- `floor`

### `run_relics`

记录遗物变化和最终签名。

建议字段：

- `run_id`
- `relic_id`
- `relic_name`
- `op`
- `floor`

### `run_tags`

记录可检索标签。

建议字段：

- `run_id`
- `tag_type`
- `tag_value`

例如：

- `boss`
- `death_enemy`
- `path_style`
- `deck_archetype`

### `run_battles`

记录战斗级索引信息。

建议字段：

- `run_id`
- `battle_id`
- `act`
- `floor`
- `enemy_signature`
- `hp_before`
- `hp_after`
- `result`

## 7. 数据流

### 7.1 局进行中

继续按 V1 方式写单局目录。

### 7.2 局结束后

做两件事：

1. 完成单局派生文件
2. 从单局目录抽取结构化数据写入 `index.sqlite`

也就是说：

- 先写 `runs/<run_id>/...`
- 后写 `archive/index.sqlite`

## 8. 检索能力

V2 至少支持：

- 查某角色的所有 run
- 查某个 Boss 的历史表现
- 查某层死亡的 run
- 查某张卡或某个遗物出现过的 run
- 查某类路径风格的 run

## 9. Prompt 使用方式

V2 默认**不直接把长期索引塞进 prompt**。

而是：

1. 先按条件查询 `index.sqlite`
2. 再抽取最相关的 3-5 条结果
3. 压缩成轻量文本
4. 再注入 prompt

所以长期索引是检索层，不是直接上下文层。

## 10. 完成标准

满足以下条件即可认为 V2 完成：

- 单局目录下已经有 `turns/`、`battles/`、`rewards/`、`derived/`
- 局结束后会写 `memory/archive/index.sqlite`
- 可以按角色 / Boss / 死亡原因 / 卡牌 / 遗物检索 run
- 单局目录和长期索引是解耦的
