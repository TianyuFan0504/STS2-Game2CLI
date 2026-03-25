# Memory V1 TODO

这个文件只记录 V1 的实现待办。

## 目标

- 给每一局生成唯一 `run_id`
- 建立 `memory/runs/<run_id>/`
- 形成最小可用的单局短期记忆

## 待办

### 1. `run_id`

- 明确 `run_id` 生成规则
- 明确何时生成：局开始时还是进入第一层时
- 明确 `latest` 的更新规则

### 2. 单局目录初始化

- 创建 `memory/runs/<run_id>/`
- 初始化：
  - `memory/summary.md`
  - `data/session.json`
  - `data/state_snapshot.json`
  - `data/ledger.jsonl`
  - `data/events.jsonl`
  - `data/agent_events.jsonl`
  - `data/runtime_prompt.md`
  - `data/iterations/`

### 3. 事件流

- 定义最小事件 schema
- 定义全局单调递增 `seq_id`
- 定义至少毫秒级时间戳
- 定义 `event_id` 只作为 `events.jsonl` 的派生字段
- 定义 V1 最小事件类型：
  - `run_started`
  - `sts2_command`
  - `state_transition`
  - `hp_change`
  - `floor_change`
  - `gold_change`
  - `run_ended`
- 定义 agent / artifact 也统一写入 `ledger.jsonl`
  - `agent_event`
  - `runtime_prompt`
  - `iteration_artifacts`

### 4. 摘要层

- 定义 `summary.md` 模板
- 定义 `state_snapshot.json` 模板
- 定义 `session.json` 字段

### 5. 写入时机

- 局开始
- 每次 `sts2` 命令成功后
- 每次 `decision` 变化后
- 每次 HP / 楼层 / 金币变化后
- 局结束

### 6. Prompt 注入

- 只注入当前 run 的 `memory/summary.md`
- 不注入：
  - `data/ledger.jsonl`
  - `data/events.jsonl`
  - `data/agent_events.jsonl`
  - 历史 run
  - 长期经验

### 7. 验收

- 每一局有独立目录
- 每一局有完整最小文件集
- agent 可读取当前局摘要
