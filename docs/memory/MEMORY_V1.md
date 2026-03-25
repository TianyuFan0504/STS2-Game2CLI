# Memory V1

## 1. 目标

V1 只做最小可实现范围，不直接碰复杂检索和策略学习。

目标只有三个：

1. 给每一局分配唯一 `run_id`
2. 把该局数据完整落到 `memory/runs/<run_id>/`
3. 让 agent 能读取单局短期摘要，但不引入复杂长期记忆检索

## 2. V1 范围

### 2.1 必做

- 单局目录结构
- `run_id` 生成规则
- 事件流落盘
- 单局摘要落盘
- 当前状态快照落盘
- 局结束结果落盘

### 2.2 不做

- SQLite 长期索引
- 跨局 lessons 检索
- 自动策略抽取
- 多级压缩
- 向量检索或 embedding

## 3. 目录结构

V1 只要求这些文件存在：

```text
memory/
├── runs/
│   └── <run_id>/
│       ├── memory/
│       │   └── summary.md
│       └── data/
│           ├── session.json
│           ├── state_snapshot.json
│           ├── ledger.jsonl
│           ├── events.jsonl
│           ├── agent_events.jsonl
│           ├── runtime_prompt.md
│           └── iterations/
│               └── <iteration>/
│                   ├── pi.raw.jsonl
│                   └── pi.log
└── latest
```

说明：

- `runs/<run_id>/`：单局主目录
- `memory/`：给模型可见的压缩摘要
- `data/`：不给模型直接看的结构化与原始数据
- `latest`：指向当前活动 run

## 4. `run_id` 规则

建议：

```text
<yyyyMMdd-HHmmss>-<character>-a<ascension>-<random6>
```

示例：

```text
20260324-194512-ironclad-a0-x7k2qm
```

V1 要求：

- 同一局只生成一次
- 整局生命周期内保持不变
- 所有单局文件都以它作为归档根路径

## 5. 文件定义

### 5.1 `session.json`

保存单局元信息。

V1 最小字段：

- `run_id`
- `status`
- `character`
- `ascension`
- `seed`
- `started_at`
- `ended_at`
- `result`
- `latest_act`
- `latest_floor`

### 5.2 `events.jsonl`

保存从 `ledger.jsonl` 派生出来的业务事件视图。

V1 最小事件类型：

- `run_started`
- `sts2_command`
- `state_transition`
- `hp_change`
- `floor_change`
- `gold_change`
- `run_ended`

V1 最小字段：

- `seq_id`
- `event_id`
- `ts`
- `ts_ms`
- `run_id`
- `event_type`
- `act`
- `floor`
- `decision`
- `payload`

### 5.3 `ledger.jsonl`

保存单局唯一主记录。

V1 当前约束：

- 所有事件统一先写这里
- 每条记录带全局单调递增 `seq_id`
- 时间戳至少毫秒级
- `events.jsonl` 和 `agent_events.jsonl` 都是它的派生视图

### 5.4 `state_snapshot.json`

保存最近一次状态。

V1 最小字段：

- `captured_at`
- `normalized_state`
- `raw_bridge_state`
- `derived_summary`

### 5.5 `summary.md`

给模型和人类都能快速看懂的单局短期摘要。

当前实现已经包含：

1. Run Header
2. Current Situation
3. Current Decision Details
4. Route So Far
5. Recent Commands
6. Recent State Changes
7. Agent Usage Note

### 5.6 `agent_events.jsonl`

保存从 `ledger.jsonl` 派生出来的 agent 侧事件视图，但默认不注入模型。

当前实现会写入：

- `thinking_delta`
- `assistant_text_delta`
- `assistant_done`
- `tool_start`
- `tool_end`
- `tool_error`

### 5.7 `data/iterations/`

保存每轮 agent 调用过程的原始日志和可读日志。

当前会写：

- `pi.raw.jsonl`
- `pi.log`

### 5.8 `runtime_prompt.md`

保存当前 run 最近一次写入的运行期 prompt 文本。

它属于运行期数据，放在 `run_id/data/` 下，而不是独立散落在外部 session 目录。

## 6. 写入时机

V1 只在这些时机写入：

1. 局开始时
2. 每次 `sts2` 命令成功后
3. 每次 state 的 `decision` 变化后
4. HP / 楼层 / 金币变化后
5. 局结束时

## 7. Prompt 注入

V1 只允许注入：

- 当前 `sts2 state`
- 当前 run 的 `memory/summary.md`

当前实现行为：

- 每次新的 agent iteration 构造 prompt 时，都会重新读取当前 run 的 `summary.md`
- 也就是说，只要当前 run 还活着，这份 summary 在每轮里都会给 agent 看到

不注入：

- `ledger.jsonl`
- 全量 `events.jsonl`
- `agent_events.jsonl`
- 历史 run
- 长期经验

## 8. 与长期记忆的关系

V1 不做长期记忆实现，但为 V2 预留：

- `run_id`
- 标准化的单局目录
- 可重扫的事件流

这样后续要做：

- `memory/archive/index.sqlite`
- 跨局检索
- 策略总结

就不需要推翻 V1。

## 9. 实现顺序

1. 先生成 `run_id`
2. 建立 `memory/runs/<run_id>/`
3. 写 `session.json`
4. 先追加 `ledger.jsonl`
5. 从 ledger 派生 `events.jsonl` / `agent_events.jsonl`
6. 维护 `state_snapshot.json`
7. 重写 `summary.md`
8. 在 prompt 中读取 `summary.md`

## 10. 完成标准

满足以下条件即可认为 V1 完成：

- 每一局都有独立目录
- 每一局都能回看事件流
- 每一局都能读到当前摘要
- agent 能在下一轮读取当前局摘要
- 不引入长期记忆复杂度
