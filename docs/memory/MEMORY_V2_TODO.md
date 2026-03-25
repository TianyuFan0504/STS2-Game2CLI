# Memory V2 TODO

这个文件只记录 V2 的实现待办。

V2 的核心不是“再多记一点”，而是把 V1 的单局目录变成**可检索、可聚合、可回放分析**的数据资产。

## 目标

- 在 V1 基础上增加跨局索引
- 为每局生成更多结构化派生数据
- 支持检索、统计和经验聚合
- 保持“单局目录是事实主存储，SQLite 只是索引层”

## 范围边界

V2 要做：

- 单局派生目录
- 局结束时的数据抽取
- `index.sqlite`
- 基础检索接口
- 基础聚合统计

V2 不做：

- embedding / 向量检索
- 自动 lesson 生成
- 自动策略修正
- 多用户共享数据库
- 远程服务化

## 一、单局派生目录

### 1.1 目录结构

在每个 `memory/runs/<run_id>/` 下新增：

- `turns/`
- `battles/`
- `rewards/`
- `derived/`

### 1.2 `turns/`

目标：按“agent 一轮决策”切片，而不是只看全量 `events.jsonl`。

待办：

- 设计 `turn_id` 规则
- 明确 turn 边界：
  - 一次 agent 启动算一轮
  - 还是一次状态变化算一轮
- 定义 `turns/<turn_id>.json` 最小字段：
  - `turn_id`
  - `run_id`
  - `started_at`
  - `ended_at`
  - `mode`
  - `decision_before`
  - `decision_after`
  - `commands`
  - `summary`

### 1.3 `battles/`

目标：每场战斗形成单独摘要，便于后续统计。

待办：

- 定义 `battle_id`
- 明确战斗开始/结束判定
- 定义 `battles/<battle_id>.json` 字段：
  - `battle_id`
  - `run_id`
  - `act`
  - `floor`
  - `room_type`
  - `enemy_names`
  - `enemy_signature`
  - `hp_before`
  - `hp_after`
  - `potions_used`
  - `turn_count`
  - `result`
  - `notes`

### 1.4 `rewards/`

目标：记录卡牌、遗物、药水、金币等奖励决策。

待办：

- 定义每层奖励文件格式
- 区分：
  - 战后奖励
  - 事件奖励
  - 宝箱奖励
  - 商店购买
- 定义 `rewards/floorXX.json` 字段：
  - `run_id`
  - `act`
  - `floor`
  - `source`
  - `options`
  - `chosen`
  - `skipped`

### 1.5 `derived/`

目标：把后续常用查询预先算出来，避免每次重扫全量事件流。

待办：

- `deck_timeline.json`
- `relic_timeline.json`
- `route_timeline.json`
- `resource_timeline.json`
- `run_tags.json`

## 二、局结束派生数据

### 2.1 结束时机

待办：

- 明确以下状态何时视为“run 结束”：
  - `game_over`
  - 胜利结算
  - 手动放弃
  - 异常中断

### 2.2 结束后生成物

待办：

- 生成 battle 摘要
- 生成 reward 汇总
- 生成最终 deck / relic / potion 签名
- 生成：
  - `postmortem.md`（失败局）
  - `victory.md`（胜利局）

### 2.3 结果标准化

待办：

- 统一 `result` 枚举：
  - `won`
  - `lost`
  - `abandoned`
  - `error`
- 统一 `death_enemy`
- 统一 `boss`
- 统一 `final_floor`

## 三、长期索引

### 3.1 SQLite 文件

待办：

- 创建 `memory/archive/index.sqlite`
- 确定 schema 版本管理方式
- 确定重建策略：删除后可由 `memory/runs/` 重建

### 3.2 表结构

至少实现这些表：

#### `runs`

待办字段：

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

#### `run_cards`

待办字段：

- `run_id`
- `card_id`
- `card_name`
- `op`
- `floor`

#### `run_relics`

待办字段：

- `run_id`
- `relic_id`
- `relic_name`
- `op`
- `floor`

#### `run_tags`

待办字段：

- `run_id`
- `tag_type`
- `tag_value`

#### `run_battles`

待办字段：

- `run_id`
- `battle_id`
- `act`
- `floor`
- `enemy_signature`
- `hp_before`
- `hp_after`
- `result`

### 3.3 索引优化

待办：

- 为 `character + ascension` 建联合索引
- 为 `boss` 建索引
- 为 `death_enemy` 建索引
- 为 `card_id` / `relic_id` 建索引
- 为 `started_at` / `ended_at` 建排序索引

## 四、检索能力

### 4.1 事实检索

待办：

- 按角色查询 run
- 按 Ascension 查询 run
- 按 Boss 查询 run
- 按死亡原因查询 run
- 按楼层范围查询 run
- 按卡牌 / 遗物查询 run

### 4.2 聚合统计

待办：

- 同角色胜率
- 平均死亡楼层
- 特定 Boss 历史表现
- 特定卡牌/遗物出现频率
- 特定路线模式分布

### 4.3 回放入口

待办：

- 给前端“重放已有结果”提供查询入口
- 支持按：
  - 最近 N 局
  - 指定 `run_id`
  - 指定角色
  - 指定结果（赢/输）
  查询可回放 run

## 五、数据流

### 5.1 写入流程

待办：

1. 运行中继续写 `memory/runs/<run_id>/...`
2. 局结束后生成派生数据
3. 局结束后把聚合字段写入 `index.sqlite`

### 5.2 重建流程

待办：

- 定义“只根据 `memory/runs/` 重建 `index.sqlite`”的流程
- 确保索引删除后不丢事实数据
- 确保 schema 升级后可重扫迁移

### 5.3 一致性策略

待办：

- 明确单局目录写成功后再写索引
- 明确失败回滚策略
- 明确局未结束时索引是否可见

## 六、Prompt 使用

### 6.1 默认策略

待办：

- 默认不注入长期索引
- 只在明确场景按需检索

### 6.2 检索后注入

待办：

- 先查 `index.sqlite`
- 再筛选最相关 run
- 再压缩成轻量文本
- 最后注入 prompt

### 6.3 注入上限

待办：

- 限制注入结果条数
- 限制注入 token 大小
- 区分“事实记录”和“策略建议”

## 七、测试与验收

### 7.1 最小验收

- 单局派生目录存在
- `index.sqlite` 可生成
- 可按角色 / Boss / 卡牌 / 遗物检索
- 前端能列出可回放 run

### 7.2 一致性验收

- 索引内容能与 `memory/runs/<run_id>/` 对上
- 删除索引后能从 `runs/` 重建
- 单局目录损坏不会拖垮全局索引重建

### 7.3 边界验收

- 异常退出的 run 如何标记
- 中途中止的 run 如何归档
- 重复写入同一 `run_id` 如何避免
