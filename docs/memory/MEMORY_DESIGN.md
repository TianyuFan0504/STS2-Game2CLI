# Memory Design

## 0. 当前落地状态

当前文档不再只是纯提案。

其中：

- **V1 已有实现骨架**
  - 实现位置：
    - `agent-harness/frontend/memory_v1.py`
    - `agent-harness/frontend/server.py`
- **V2 仍然是设计阶段**

当前 V1 已实际落地的能力：

1. 每一局会分配唯一 `run_id`
2. 每一局数据写入 `memory/runs/<run_id>/`
3. 单局目录下已生成：
   - `memory/summary.md`
   - `data/session.json`
   - `data/state_snapshot.json`
   - `data/events.jsonl`
   - `data/agent_events.jsonl`
4. `memory/latest` 会指向当前活动 run
5. 下一轮 agent prompt 会读取当前 run 的 `memory/summary.md`

当前 V1 尚未完全做完的地方：

- 还没有完整覆盖所有真实游戏边界场景
- 还没有把所有字段扩展到最终理想版本
- 还没有进入 V2 的跨局索引阶段

## 1. 设计目标

新的 memory 系统服务于两个目标：

- 让 agent 在跨 iteration 运行时具备稳定的连续性，而不是每轮只依赖当前 `sts2 state`
- 让记忆本身可审计、可回放、可压缩，不和运行时上下文混成一个不可控黑盒

设计上必须同时满足：

- 当前局面的事实优先于历史记忆
- 短期记忆优先于长期记忆
- 摘要优先于原始事件

## 2. 记忆分层

### 2.1 短期记忆

短期记忆的作用域是一整把 run。

它记录：

- `run_id`、角色、难度、seed、act、floor
- 地图路线选择
- 事件选项、休息点选择、商店购买
- 卡牌奖励、遗物奖励、药水获取/使用
- 每场战斗的关键摘要
- 当前牌组、遗物、药水、金币、HP 的变化轨迹
- 最近若干条 `sts2` 命令及结果

短期记忆的主要用途：

- 给下一轮 agent prompt 提供上下文
- 让前端展示“这一把发生了什么”
- 给局结束总结提供原材料

### 2.1.1 当前 V1 实现方式

当前 V1 的短期记忆实现不是独立服务，而是由前端控制服务在本地维护：

- `agent-harness/frontend/server.py` 在正确时机调用 `MemoryV1Store`
- `agent-harness/frontend/memory_v1.py` 负责单局目录、事件流、摘要和快照落盘

当前工作流：

1. 当前端 agent 首次看到一个非 `menu` 的状态时，开始一局 memory run
2. 生成 `run_id`
3. 建立 `memory/runs/<run_id>/`
4. 记录最初状态
5. 后续在每次关键状态变化或 `sts2` 命令后更新摘要与事件流
6. 局结束或被明确中断时，写入结束结果

也就是说，当前 V1 已经不再是概念，而是一个真实在运行链路中的组件。

### 2.2 长期记忆

长期记忆的作用域是跨 run。

它记录：

- 每一局的最终结果
- 胜负、死亡层数、死亡敌人、最终牌组和遗物概况
- 对角色、路线、卡牌、遗物、Boss 的策略总结
- 常见失败模式和高价值经验

长期记忆的主要用途：

- 给后续 run 提供经验参考
- 做跨局检索和统计
- 支撑策略层优化，而不是直接驱动每一步操作

## 3. 数据存储机制

### 3.0 总体原则

数据存储必须围绕“每一把 run 是一个独立目录”来设计。

核心要求：

- 每次游戏运行分配唯一 `run_id`
- 所有单局数据全部收敛到 `memory/runs/<run_id>/`
- 长期索引只保存聚合结果和检索入口，不直接替代单局原始数据
- 任意一局都可以脱离长期索引单独回放和审计

建议目录总览：

```text
memory/
├── runs/
│   └── <run_id>/
│       ├── session.json
│       ├── summary.md
│       ├── state_snapshot.json
│       ├── events.jsonl
│       ├── turns/
│       │   ├── 0001.json
│       │   ├── 0002.json
│       │   └── ...
│       ├── battles/
│       │   ├── act1-floor02-fuzzy-wurm-crawler.json
│       │   └── ...
│       ├── rewards/
│       │   ├── floor02.json
│       │   └── ...
│       └── derived/
│           ├── deck_timeline.json
│           ├── route_timeline.json
│           └── resource_timeline.json
├── archive/
│   ├── index.sqlite
│   └── exports/
└── latest
```

其中：

- `runs/<run_id>/` 是事实主存储
- `archive/index.sqlite` 是长期检索入口
- `latest` 指向当前活动 run

### 3.0.1 当前 V1 已实现的目录结构

当前 V1 已经实际落地的是这个最小结构：

```text
memory/
├── runs/
│   └── <run_id>/
│       ├── memory/
│       │   └── summary.md
│       └── data/
│           ├── session.json
│           ├── state_snapshot.json
│           ├── events.jsonl
│           └── agent_events.jsonl
└── latest
```

也就是说：

- `turns/`
- `battles/`
- `rewards/`
- `derived/`
- `archive/index.sqlite`

这些都还属于 V2 规划，不是当前实现。

### 3.0.1 `run_id` 设计

`run_id` 必须满足：

- 全局唯一
- 人眼可读
- 能快速看出时间和角色
- 同一秒并发启动时不冲突

建议格式：

```text
<yyyyMMdd-HHmmss>-<character>-a<ascension>-<random6>
```

例如：

```text
20260324-194512-ironclad-a0-x7k2qm
20260324-201030-silent-a10-b91cde
```

字段规则：

- 时间戳：用于排序
- 角色：便于肉眼检索
- Ascension：便于难度归类
- 随机后缀：防碰撞

可选地增加一个内部 `session_uuid`，放在 `session.json` 里，供程序级引用。

### 3.0.2 当前 V1 的 `run_id` 实现

当前实现已经使用：

```text
<yyyyMMdd-HHmmss>-<character>-a<ascension>-<random6>
```

实现位置：

- `agent-harness/frontend/memory_v1.py`

当前行为：

- 第一次进入非 `menu` 状态时生成
- 整局生命周期内保持不变
- 用作单局目录名

当前限制：

- 是否在“第一层地图”还是“第一次非 menu 状态”启动 run，仍然是实现策略，不是协议层固化约束

### 3.1 事件层

事件层保存最细粒度记录，采用 JSONL。

建议目录：

```text
memory/runs/<run_id>/events.jsonl
```

建议再拆一个逻辑层：

- `events.jsonl`：统一事件流，严格按时间排序
- `turns/<turn_id>.json`：按“决策轮次”切片

这样有两个好处：

- 调试时可以从全量事件流看时间顺序
- prompt 构建时可以只读取最近若干 turn

每条事件至少包含：

- `ts`
- `event_type`
- `act`
- `floor`
- `decision`
- `payload`

事件类型包括：

- `sts2_command`
- `state_transition`
- `hp_change`
- `floor_change`
- `gold_change`
- `battle_start`
- `battle_end`
- `reward_pick`
- `event_choice`
- `shop_purchase`
- `rest_choice`

建议补充事件类型：

- `run_started`
- `run_ended`
- `room_entered`
- `game_over`
- `victory`
- `potion_used`
- `relic_gained`
- `card_added`
- `card_removed`
- `card_upgraded`
- `manual_override`
- `agent_prompt_started`
- `agent_prompt_finished`

建议统一事件结构：

```json
{
  "event_id": "evt_0000001234",
  "ts": "2026-03-24T19:45:12.512Z",
  "run_id": "20260324-194512-ironclad-a0-x7k2qm",
  "turn_id": "turn_00017",
  "event_type": "sts2_command",
  "act": 1,
  "floor": 6,
  "decision": "combat_play",
  "payload": {
    "command": "sts2 play-card 3 --target BYRDONIS_0",
    "result": "ok"
  }
}
```

设计要求：

- `event_id` 单调递增，便于断点读取
- `turn_id` 用于把多条命令归到同一轮决策
- `payload` 保持 schema 宽松，便于以后扩展

### 3.1.2 当前 V1 的事件层实现

当前实现已经使用：

- `data/events.jsonl`
- 追加写入
- 单局独立文件

当前已落地的事件类型包括：

- `run_started`
- `sts2_command`
- `state_transition`
- `hp_change`
- `floor_change`
- `gold_change`
- `run_ended`

当前事件字段包括：

- `event_id`
- `ts`
- `run_id`
- `event_type`
- `act`
- `floor`
- `decision`
- `text`
- `payload`

当前限制：

- 还没有 `turn_id`
- 还没有 battle/reward 级单独事件文件

### 3.1.1 Turn 层

`turns/` 目录的目标不是替代事件流，而是给模型提供“更自然的轮次摘要”。

建议每个 turn 存：

- `turn_id`
- `started_at` / `ended_at`
- 当轮输入 prompt 摘要
- 当轮初始状态摘要
- 当轮执行的 `sts2` 命令列表
- 当轮结束状态摘要
- 当轮 assistant 最终结论

示例：

```json
{
  "turn_id": "turn_00017",
  "run_id": "20260324-194512-ironclad-a0-x7k2qm",
  "started_at": "2026-03-24T19:48:01.201Z",
  "ended_at": "2026-03-24T19:48:05.992Z",
  "mode": "micro_step",
  "decision_before": "combat_play",
  "decision_after": "combat_play",
  "commands": [
    "sts2 play-card 3 --target BYRDONIS_0"
  ],
  "summary": "Played Pommel Strike on Byrdonis and stayed in combat."
}
```

### 3.2 会话摘要层

摘要层保存单局压缩记忆，直接供 prompt 使用。

建议目录：

```text
memory/runs/<run_id>/summary.md
memory/runs/<run_id>/state_snapshot.json
memory/runs/<run_id>/session.json
```

其中：

- `summary.md` 面向模型阅读
- `state_snapshot.json` 面向程序恢复和调试
- `session.json` 记录 run 元信息

建议再增加：

```text
memory/runs/<run_id>/checkpoints/
```

里面保存阶段性摘要，例如：

- `floor-01.md`
- `floor-05.md`
- `boss-prep.md`

这些 checkpoint 不一定默认注入 prompt，但适合做回顾和局中压缩。

### 3.2.4 当前 V1 的摘要层实现

当前已实现：

- `data/session.json`
- `memory/summary.md`
- `data/state_snapshot.json`
- `data/agent_events.jsonl`

#### `session.json`

当前实际字段包括：

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
- `latest_event_id`
- `last_hp`
- `last_max_hp`
- `last_gold`

#### `state_snapshot.json`

当前实际字段包括：

- `captured_at`
- `normalized_state`
- `raw_bridge_state`
- `derived_summary`

#### `summary.md`

当前已经包含：

- Run Header
- Current Situation
- Route So Far
- Recent Commands
- Recent State Changes
- Agent Usage Note

当前限制：

- 还没有更细的 battle/reward 汇总
- 路线展示仍依赖当前状态里是否带 `visited`

### 3.2.1 `session.json` 深化设计

`session.json` 作为 run 根元数据，建议包含：

- `run_id`
- `session_uuid`
- `status`：`active | won | lost | abandoned | error`
- `character`
- `ascension`
- `seed`
- `started_at`
- `ended_at`
- `game_version`
- `bridge_version`
- `provider`
- `model`
- `frontend_session_id`
- `latest_turn_id`
- `latest_event_id`
- `latest_floor`
- `latest_act`

### 3.2.2 `state_snapshot.json` 深化设计

这个文件不应只保存最后一次原始状态，而应明确保存：

- `normalized_state`
- `raw_bridge_state`
- `captured_at`
- `derived_summary`

这样可以区分：

- 给程序恢复用的结构化状态
- 给调试用的底层桥接状态
- 给前端显示用的压缩摘要

### 3.2.3 `summary.md` 深化设计

`summary.md` 应该控制在适合 prompt 注入的规模内。

建议结构：

1. Run Header
2. Current Situation
3. Route So Far
4. Deck / Relic / Potion Delta
5. Recent Fights
6. Recent Commands
7. Immediate Tactical Notes
8. Open Risks

控制原则：

- 面向模型，不面向人类报告
- 重点是“当前还需要记住什么”
- 不追求完整回放

### 3.3 长期索引层

长期索引层保存跨局聚合数据。

建议目录：

```text
memory/archive/index.sqlite
```

如果早期不引入 SQLite，可先用：

```text
memory/archive/index.json
```

长期索引至少应支持按以下维度查询：

- 角色
- Ascension
- Boss
- 死亡敌人
- 卡牌
- 遗物
- 关键词标签

### 3.3.1 长期索引表设计

如果采用 SQLite，建议至少包含这些表：

#### `runs`

- `run_id` TEXT PRIMARY KEY
- `session_uuid` TEXT
- `started_at` TEXT
- `ended_at` TEXT
- `character` TEXT
- `ascension` INTEGER
- `seed` TEXT
- `result` TEXT
- `final_act` INTEGER
- `final_floor` INTEGER
- `death_enemy` TEXT
- `boss` TEXT
- `final_hp` INTEGER
- `final_gold` INTEGER
- `summary_path` TEXT
- `events_path` TEXT

#### `run_cards`

- `run_id`
- `card_id`
- `card_name`
- `op` (`added|removed|upgraded|final`)
- `floor`

#### `run_relics`

- `run_id`
- `relic_id`
- `relic_name`
- `op` (`gained|lost|final`)
- `floor`

#### `run_tags`

- `run_id`
- `tag_type` (`boss|elite|strategy|failure_mode|card_synergy`)
- `tag_value`

#### `run_lessons`

- `run_id`
- `scope` (`tactical|strategic`)
- `lesson`
- `confidence`

这样长期记忆就既能查“事实”，也能查“经验”。

### 3.3.2 长期索引和单局目录的关系

长期索引只保存：

- 检索字段
- 汇总字段
- 文件路径指针

单局真实内容仍然在：

- `memory/runs/<run_id>/...`

也就是说：

- 删掉索引后，单局事实仍然存在
- 重建索引时，只需要重新扫描 `runs/`

## 4. 生命周期设计

### 4.1 单局开始

创建新的 `run_id`，初始化：

- `events.jsonl`
- `summary.md`
- `state_snapshot.json`
- `session.json`
- `turns/`
- `derived/`

并更新：

- `memory/latest -> runs/<run_id>`

### 4.1.1 初始化动作

初始化时应明确写入一条：

- `run_started`

并固定本局的：

- 角色
- ascension
- seed
- provider
- model
- 启动入口（frontend / cli / manual）

### 4.1.2 当前 V1 生命周期实现

当前实现大致如下：

#### 单局开始

- 第一次收到非 `menu` 状态时触发
- 生成 `run_id`
- 创建单局目录
- 写第一次 `state_snapshot.json`
- 写 `run_started` 事件

#### 单局进行中

- 每次关键 `sts2` 命令后写 `sts2_command`
- 每次状态变化后写：
  - `state_transition`
  - `hp_change`
  - `floor_change`
  - `gold_change`
- 同时重写 `summary.md`

#### 单局结束

当前实现会在这些情况下结束单局：

- 状态进入 `menu`，并且上一状态不是 `menu`
- 或者显式调用 `finalize_if_active(...)`

当前 `result` 判定仍然比较保守：

- 如果上一状态是 `game_over`，判为 `lost`
- 否则可能落成 `unknown` 或 `interrupted`

### 4.2 单局进行中

在这些时机写入短期记忆：

- 状态切换后
- 执行 `sts2` 命令后
- 战斗结束后
- 奖励选择后
- 每层推进后

建议加入更具体的写入触发点：

- 每次 `sts2 state` 产生 decision 变化
- 每次 `sts2` 命令执行完成
- 每次进入战斗 / 离开战斗
- 每次 deck、relic、potion、gold、hp 发生变化
- 每次 agent 输出最终结论

### 4.2.1 单局内压缩

建议使用“事件保留、摘要滚动”的方式：

- `events.jsonl` 永不覆盖
- `summary.md` 每次增量重写
- `turns/*.json` 可按轮落盘
- `checkpoints/*.md` 在关键楼层生成

### 4.3 单局结束

当进入 `game_over` 或胜利结算时：

- 冻结本局摘要
- 生成整局总结
- 写入长期索引

建议局结束时再生成：

- `postmortem.md`（失败局）
- `victory.md`（胜利局）

这两个文档用于长期经验抽取，不直接注入下一局 prompt。

## 5. Prompt 注入策略

### 5.1 短期记忆注入

默认只注入当前 run 的 `summary.md`。

不直接注入：

- 全量 `events.jsonl`
- 全量 raw state
- 过长的战斗逐步记录

建议再加一层限制：

- 默认最多注入最近一次生成的 `summary.md`
- 如需补充，只允许再注入最近 3 个 `turns/*.json`
- 不允许直接把 `events.jsonl` 原样注入

### 5.1.1 当前 V1 的 prompt 注入实现

当前实现已经把短期记忆注入下一轮 prompt。

方式是：

- 前端控制服务在构造 agent prompt 时，读取当前活动 run 的 `memory/summary.md`
- 然后把这份摘要作为“current-run summary”拼进 prompt

当前注入内容：

- 只注入当前活动 run 的 `memory/summary.md`

当前行为细节：

- 每次新的 agent iteration 构造 prompt 时，都会重新读取当前活动 run 的 `summary.md`
- 只要当前 run 还在进行，这份 summary 就会继续进入下一轮上下文
- 它不是“局开始时注入一次”，而是“每轮都读取最新版本”

当前不注入：

- `data/events.jsonl`
- `data/agent_events.jsonl`
- 其他 run
- 长期经验

### 5.2 长期记忆注入

长期记忆不应默认注入。

只有在这些场景才按需检索：

- 局开始前做路线规划
- 遇到特定 Boss / 精英 / 事件
- 用户要求策略复盘

建议长期检索结果也不要直接全量注入，而是先压缩成：

- `lessons_top_k.md`

其中只保留最相关的 3-5 条经验。

### 5.3 注入优先级

优先级从高到低：

1. 当前 `sts2 state`
2. 当前 run 的短期摘要
3. 按需检索出的长期经验

## 6. 建议的数据格式

### 6.1 `session.json`

建议字段：

- `run_id`
- `character`
- `ascension`
- `seed`
- `started_at`
- `ended_at`
- `result`
- `provider`
- `model`
- `frontend_session_id`
- `latest_event_id`
- `latest_turn_id`

### 6.2 `summary.md`

建议分段：

- Run Header
- Current Situation
- Route History
- Battle Summary
- Resource Changes
- Recent Commands
- Open Questions / Risks

建议再增加：

- Last 10 Commands
- Last State Transition
- Last HP Change
- Current Planning Horizon

### 6.3 长期索引记录

每条 run 记录建议包括：

- `run_id`
- `character`
- `ascension`
- `result`
- `final_floor`
- `boss`
- `death_enemy`
- `deck_tags`
- `relic_tags`
- `strategy_notes`

建议再加：

- `summary_path`
- `events_path`
- `deck_signature`
- `relic_signature`
- `route_signature`

## 7. 压缩与保留策略

### 7.1 短期记忆压缩

当单局事件过多时：

- 保留全部原始事件到 `events.jsonl`
- 只压缩 `summary.md`
- 将早期战斗细节归纳为更短摘要

建议压缩规则：

- 保留最近 10 层的详细变化
- 更早楼层只保留 checkpoint 摘要
- 战斗逐手日志只保留最近 3 场或关键战

### 7.2 长期保留

建议：

- `events.jsonl` 长期保留，但可归档
- `summary.md` 永久保留
- `index.sqlite` 永久保留

进一步建议：

- `turns/*.json` 可在归档后压缩成 `turns.tar.zst`
- `state_snapshot.json` 保留最后一次即可
- 关键局（胜利局、Boss 局、异常失败局）永久热存

## 8. 风险与边界

- memory 不能覆盖当前 `sts2 state`
- 历史经验不能被当成当前事实
- 一次偶然成功不能直接固化为长期规则
- 长期记忆必须区分“事实记录”和“策略判断”
- 不能让单局目录结构依赖长期索引才能读取
- 不能让不同 run 共享同一个活动文件，避免串局

## 9. 推荐实现顺序

1. 单局事件流
2. 单局摘要
3. 局结束总结
4. 跨局索引
5. 按需检索和策略注入
