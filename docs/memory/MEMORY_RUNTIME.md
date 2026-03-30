# Memory Runtime Mechanism

这份文档解释**当前代码里已经实际运行的 Memory V1 / V2 机制**。

它关注的是：

- 前端控制服务在每轮 agent iteration 里如何驱动 memory
- V1 在运行中如何写单局短期记忆
- V2 在 run 结束后如何做派生与归档

它不重复设计稿里的未来目标，也不把“想做什么”和“现在怎么做”混在一起。

## 1. 角色分工

当前 memory 运行机制主要分成三层：

### 1.1 控制层

文件：

- `agent-harness/frontend/server.py`

职责：

- 驱动每轮 agent iteration
- 读取游戏状态
- 把 pi 的事件流转成 memory 可消费的数据
- 决定什么时候写 prompt、什么时候写 turn、什么时候结束 run

### 1.2 运行中短期记忆层

文件：

- `agent-harness/frontend/memory_v1.py`

职责：

- 维护当前活动 run
- 在 run 进行中持续写：
  - `session.json`
  - `state_snapshot.json`
  - `ledger.jsonl`
  - `events.jsonl`
  - `agent_events.jsonl`
  - `runtime_prompt.md`
  - `memory/summary.md`
- 管理 `memory/latest`
- 决定 run 生命周期

### 1.3 局后派生与索引层

文件：

- `agent-harness/frontend/memory_v2.py`

职责：

- 在 run 结束后读取 V1 已落盘的数据
- 生成：
  - `turns/`
  - `battles/`
  - `rewards/`
  - `derived/`
- 更新：
  - `memory/archive/index.sqlite`

## 2. 总体数据流

当前每轮 iteration 的主路径是：

1. 前端控制服务读取当前 `sts2 state`
2. `MemoryV1Store.record_state(..., source="iteration_start")`
3. `MemoryV1Store.prepare_turn(...)`
4. 组合 prompt，把当前 run 的 `summary.md` 注入 agent
5. 启动 `pi`，收集 JSON 事件流
6. 逐条处理 agent 事件、工具事件和 `sts2 ...` 命令
7. 保存本轮 `pi.raw.jsonl` / `pi.log` / `runtime_prompt.md`
8. 再次读取 `sts2 state`
9. `MemoryV1Store.record_state(..., source="iteration_end")`
10. 如果 run 在这一轮结束，则调用 V2 做局后派生和索引

可以把它理解成：

- V1 是“边跑边记”
- V2 是“收官归档”

## 3. V1 运行机制

## 3.1 启动与恢复

`MemoryV1Store` 初始化时会做两件事：

1. 确保 `memory/` 和 `memory/runs/` 目录存在
2. 尝试从磁盘恢复最近一个 run

恢复逻辑优先级是：

1. `memory/latest`
2. 如果 `latest` 不可用，则退回到 `memory/runs/` 里按目录排序的最后一个 run

如果这个 run 的 `session.json` 仍然是 active 状态，就会恢复为当前活动 run，并重建：

- `latest_summary`
- `latest_state`
- `seq_counter`
- 最近命令列表
- 最近状态变化列表

这保证了：

- 前端重启后不会丢掉当前局
- prompt 仍然能接着注入当前局摘要

## 3.2 run 何时开始

当前 run 的开始条件不是“开程序时”，而是：

- 第一次观察到非 `menu` 状态时

具体策略是：

- 如果当前没有 active run，且当前 `sts2 state` 的 `decision != menu`
- 就创建新的 `run_id`
- 建立 `memory/runs/<run_id>/`

如果 agent 在主菜单先发了：

- `start-game`
- `continue-game`

但状态还没切出去，V1 不会立刻开 run，而是先把这条命令记成 `pending_new_run`。

等到下一次真正看到非 `menu` 状态时，再：

- 用当前状态创建 run
- 把 `pending_new_run` 合并进 run 的初始信息

这样可以避免把“还没真正进入游戏”的菜单阶段错误记录成新 run。

## 3.3 run_id 与目录

当前 `run_id` 格式是：

```text
<yyyyMMdd-HHmmss>-<character>-a<ascension>-<random6>
```

对应目录结构是：

```text
memory/runs/<run_id>/
├── data/
│   ├── session.json
│   ├── state_snapshot.json
│   ├── ledger.jsonl
│   ├── events.jsonl
│   ├── agent_events.jsonl
│   ├── runtime_prompt.md
│   └── iterations/
└── memory/
    └── summary.md
```

同时：

- `memory/latest` 会被更新到这个 run

## 3.4 每轮 iteration 中 V1 写什么

### 3.4.1 iteration 开始

前端控制服务在每轮 iteration 开始时会先读取一次游戏状态。

然后会调用：

- `record_state(..., source="iteration_start")`
- `prepare_turn(iteration, mode, state)`

这一步会做：

- 更新当前 run 的最新摘要和状态快照
- 刷新 `session.json`
- 追加必要事件到 `ledger.jsonl` / `events.jsonl`
- 写入一个 `turn_started` artifact

`turn_started` 是 V2 重建 `turns/` 的关键锚点。

它当前会保存：

- `iteration`
- `mode`
- `state_summary`
- 完整的 `state`

### 3.4.2 prompt 写入

控制服务会读取：

- 基础 prompt
- 当前活动 run 的 `memory/summary.md`

然后组合成这轮给 pi 的运行时 prompt。

这份 prompt 会被写到：

- `data/runtime_prompt.md`

并在 `ledger.jsonl` 里记一条 `runtime_prompt` artifact。

### 3.4.3 pi 事件流处理

pi 运行时输出 JSON 事件流。

前端控制服务会逐条解析这些事件，并把它们分三路处理：

#### a. 前端 UI 展示

这些事件会先进入前端自己的 live timeline。

#### b. V1 的 agent 侧事件记录

每条 pi 事件都会调用：

- `record_agent_event(...)`

写入：

- `ledger.jsonl`
- `agent_events.jsonl`

当前已经记录的典型事件包括：

- `thinking_delta`
- `assistant_text_delta`
- `assistant_done`
- `tool_start`
- `tool_end`
- `tool_error`

#### c. `sts2` 命令和状态写入

当 pi 发起 `bash` 工具调用时，前端会从命令文本里抽取：

- `sts2 ...` 片段

在 `tool_end` 成功后：

- 成功执行的 `sts2` 命令会被记成 `sts2_command`
- 如果命令是 `start-game` / `continue-game`，则会进入 `pending_new_run`
- 如果命令里包含 `sts2 state`，前端还会直接解析输出，再调用一次 `record_state(..., source="agent_state_command")`

这意味着：

- V1 不只依赖 iteration 开头和结尾的状态
- 还会吸收 iteration 内部显式执行的 `sts2 state`

## 3.5 iteration 结束

当 pi 这一轮结束后，控制服务会：

1. 把本轮临时日志移动到当前 run 的 `data/iterations/<iteration>/`
2. 记录 `iteration_artifacts`
3. 再次读取真实 `sts2 state`
4. 调用 `record_state(..., source="iteration_end")`

这一轮的最终状态会成为：

- `latest_summary`
- `latest_state`
- `state_snapshot.json`
- `summary.md`

## 3.6 V1 的事件模型

V1 的唯一主记录是：

- `data/ledger.jsonl`

它包含三类记录：

- `event`
- `agent_event`
- `artifact`

其中：

- `events.jsonl` 是从 `event` 派生出来的业务事件视图
- `agent_events.jsonl` 是从 `agent_event` 派生出来的 agent 事件视图

当前 V1 常见业务事件包括：

- `run_started`
- `sts2_command`
- `state_transition`
- `hp_change`
- `floor_change`
- `gold_change`
- `act_change`
- `run_ended`

所有记录都共享：

- `seq_id`
- `ts`
- `ts_ms`
- `run_id`
- `act`
- `floor`
- `decision`

## 3.7 `summary.md` 如何维护

`summary.md` 是 V1 直接给模型看的压缩记忆。

它在状态变化、命令写入、run 结束时会被重写。

当前内容主要包括：

- Run Header
- Current Situation
- Current Decision Details
- Route So Far
- Recent Commands
- Recent State Changes
- Agent Usage Note

这个文件不是事实源，只是 prompt 用的压缩视图。

事实源仍然是：

- 当前 `sts2 state`
- 当前 run 的结构化数据文件

## 3.8 run 何时结束

当前 run 的结束条件主要有三类：

### a. 进入不可继续的 `menu`

如果从非 `menu` 状态回到 `menu`，并且这个 `menu` 不再代表“同一局仍可继续”，那么 run 会结束。

这覆盖了：

- 游戏结束后回主菜单
- 放弃 run 后回主菜单

### b. 新 run 即将开始

如果当前已有 active run，且 agent 又发出了新的：

- `start-game`
- `continue-game`

之后又观测到一个明显属于新局的非 `menu` 状态，V1 会先结束上一局，再开始下一局。

### c. 显式 finalize

控制流也可以显式调用：

- `finalize_if_active(...)`

例如在某些需要强制收口的场景中。

## 3.9 result 如何判定

当前 result 判定已经比最初版本更稳定，但仍然是偏保守的规则：

- `game_over` 且 HP > 0：`won`
- `game_over` 且 HP <= 0：`lost`
- 主菜单执行 `abandon-game` 后失去可继续入口：`abandoned`
- 其他无法明确判断的结束：保留 `unknown` / `finished`

## 3.10 V1 与 prompt 的关系

当前 prompt 注入规则非常严格：

只注入：

- 当前 `sts2 state`
- 当前活动 run 的 `memory/summary.md`

不注入：

- 历史 run
- `events.jsonl`
- `agent_events.jsonl`
- `ledger.jsonl`
- `index.sqlite`

也就是说：

- V1 是当前局短期记忆
- V2 不是默认 prompt 上下文

## 4. V2 运行机制

## 4.1 触发时机

V2 不是在 run 进行中增量写，而是在：

- `MemoryV1Store._finalize_run(...)`

里调用：

- `MemoryV2Archive.materialize_run(run_dir)`

所以当前模型是：

- V1 负责“在线”
- V2 负责“局后归档”

## 4.2 V2 的输入源

V2 只读取 V1 已经落盘的数据，不直接读前端 live 内存。

当前主要输入是：

- `data/session.json`
- `data/state_snapshot.json`
- `data/events.jsonl`
- `data/ledger.jsonl`

这保证了：

- V2 可以从磁盘重建
- `index.sqlite` 不是主数据

## 4.3 `materialize_run` 做什么

当前 `materialize_run(run_dir)` 的顺序是：

1. 读取 session / snapshot / events / ledger
2. 确保 `turns/` / `battles/` / `rewards/` / `derived/` 目录存在
3. 清掉这些目录里旧的 JSON 派生文件
4. 重建 `turns`
5. 重建 `rewards`
6. 重建 `battles`
7. 重建：
   - `deck_timeline.json`
   - `relic_timeline.json`
   - `route_timeline.json`
   - `resource_timeline.json`
   - `run_tags.json`
8. 刷新 `index.sqlite`

## 4.4 `turns/` 如何生成

V2 当前通过 `ledger.jsonl` 里的 `turn_started` artifact 来切 turn。

切分方式是：

- 每看到一个新的 `turn_started`
- 就把前一个 turn 收尾
- 然后把后续记录继续归入当前 turn

每个 turn 会收集：

- `state_before`
- `state_before_details`
- `state_after`
- 本轮命令列表
- assistant 输出
- prompt / raw log / text log 路径

注意：

- `state_before` 是压缩摘要
- `state_before_details` 是 prepare_turn 时保存的完整状态

这个完整状态是后面 reward / card / relic 提取的重要基础。

## 4.5 `rewards/` 如何生成

V2 当前按 turn 的 `decision_before` 判断它是不是 reward 类 turn。

当前覆盖：

- `combat_rewards`
- `card_reward`
- `event_choice`
- `rest_site`
- `shop`
- `card_select`
- `relic_select`
- `treasure`

每个 reward 文件的核心来源是：

- `turn.state_before_details`
- 该 turn 中真正执行成功的 `sts2` 命令

V2 会做：

1. 从状态里提取 `options`
2. 从命令里识别本轮真正的选择动作
3. 把动作和 `options` 对应起来
4. 写出：
   - `options`
   - `chosen`
   - `chosen_command`
   - `skipped`

当前 reward 仍然不是完整 replay 层，因为：

- 有些多阶段 UI 流程还需要跨 turn 追踪
- 现在还是“当前 turn 视角”

## 4.6 `battles/` 如何生成

V2 不是直接从战斗日志对象生成 battle，而是：

- 把连续的 combat turns 聚成一个 battle

当前 combat turn 判定来自：

- `decision_before in {"combat_play", "hand_select"}`
- 或 `decision_after in {"combat_play", "hand_select"}`

battle 当前会提取：

- `act`
- `floor`
- `room_type`
- `enemy_names`
- `enemy_signature`
- `hp_before`
- `hp_after`
- `turn_count`
- `result`
- `turn_ids`
- `commands`

当前 `enemy_names` / `enemy_signature` 主要依赖：

- `state_before_details` 里保存的战斗状态

## 4.7 `derived/` 如何生成

当前 `derived/` 里已经有五类文件：

### a. `deck_timeline.json`

保存当前已识别出的 card delta 事件。

当前会从这些场景抽卡牌变化：

- `card_reward`
- `shop` 买卡
- `combat_rewards` 里的 card 类奖励
- `card_select` 里的 upgrade / remove / transform / duplicate 类动作

### b. `relic_timeline.json`

保存当前已识别出的 relic delta 事件。

当前会从这些场景抽遗物变化：

- `shop` 买 relic
- `treasure`
- `relic_select`
- `event_choice`
- `combat_rewards` 里的 relic 类奖励

### c. `route_timeline.json`

保存路线推进结果。

来源优先级：

1. 最终状态里的 `visited`
2. `session.json` 里的 `route_history`

### d. `resource_timeline.json`

保存：

- HP
- Gold
- Floor
- Act

的变化时间线。

它直接来自 `events.jsonl` 里的资源变化事件。

### e. `run_tags.json`

保存当前可检索标签。

当前已写入的标签包括：

- `character`
- `result`
- `ascension`
- `final_act`
- `final_floor`
- `latest_decision`
- `boss`
- `death_enemy`
- `turn_count`
- `battle_count`
- `reward_count`
- `card_event_count`
- `relic_event_count`

## 4.8 SQLite 如何更新

当前 `index.sqlite` 包含这些表：

- `runs`
- `run_cards`
- `run_relics`
- `run_tags`
- `run_battles`

写入策略是：

- 每次 `materialize_run` 都先删掉这个 `run_id` 在派生表中的旧记录
- 再把当前重建结果重新写进去

也就是说，当前策略是：

- run 目录是事实源
- SQLite 是可重建索引层

## 4.9 当前已支持的检索

V2 当前已经提供最小查询接口：

- `find_runs(...)`
- `find_runs_by_tag(...)`
- `find_battles(...)`
- `find_card_events(...)`
- `find_relic_events(...)`

这些查询目前主要给后端和测试使用，还没有前端 replay/search UI。

## 5. 当前一致性边界

当前实现里有三条很重要的边界：

### 5.1 V1 是运行中主写入层

只要 run 还没结束：

- 所有事实数据以 V1 为准

### 5.2 V2 只在局后 materialize

当前不会在 run 进行中持续刷新 `index.sqlite`。

所以：

- 活动局的最新 turn / reward / battle 信息
- 不保证已经出现在 SQLite 里

### 5.3 prompt 不读取 V2

当前 agent prompt 只读取：

- 当前 `sts2 state`
- 当前 run 的 `summary.md`

不会读取：

- `turns/*.json`
- `battles/*.json`
- `rewards/*.json`
- `derived/*.json`
- `index.sqlite`

## 6. 当前还没做完的部分

虽然现在 memory 已经能稳定运行，但还没有完全收尾。

还明显没做完的包括：

- battle 的更细 enemy / room 结构
- reward 的完整 replay 语义
- 更丰富的 deck / relic 语义提取
- 聚合统计
- 前端 replay / search API
- 跨局 lesson 抽取

## 7. 一句话总结

当前实际机制可以概括成：

- `server.py` 驱动每轮 iteration
- `memory_v1.py` 在 run 进行中持续写短期记忆
- `memory_v2.py` 在 run 结束后重建 turn/reward/battle/derived，并刷新 SQLite

也就是说：

- V1 负责“在线记忆”
- V2 负责“离线归档与索引”
