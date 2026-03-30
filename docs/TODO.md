# STS2CLI TODO

## 当前状态

当前项目已经具备这些基础能力：

- 通过桥接插件控制真实 Steam 版游戏
- 通过 `sts2` CLI 暴露原子控制命令
- 通过 `pi` harness 驱动 agent 自动游玩
- 通过浏览器前端控制 agent、查看状态和日志
- Memory V1 已完成：单局短期记忆目录、事件流、摘要和 prompt 注入已经接入前端控制服务，并有基础回归测试
- Memory V2 已推进到结构化归档阶段：局结束后会生成 `turns/` / `battles/` / `rewards/` / `derived/`，并维护 `memory/archive/index.sqlite`、`run_cards`、`run_relics`

## 下一阶段重点

### 1. Game Flow

- 验证死亡后 `game_over -> return_to_main_menu -> menu -> start-game/continue-game` 全链路稳定性
- 让 agent 在游戏结束后稳定自动开下一把
- 补齐更多主菜单/局后界面状态识别

### 2. Frontend

- 支持“重放已有结果”
- 支持“开一局新的游戏”
- 地图面板显示完整地图，而不是只看下一层选项
- 优化系统事件时间线展示
- 增加筛选器：思考 / 命令 / 系统事件
- 增加一键打开浏览器的启动入口

### 3. Agent Behavior

- 修正微步进模式，确保严格只执行一条状态变化命令
- 提升地图路径选择质量
- 提升战斗决策质量，减少低级失误
- 提升局后流程处理能力（奖励、商店、事件、游戏结束）

### 4. Memory V1 Regression

- 新增状态类型或命令流后，补充 Memory V1 回归测试
- 持续验证 `run_id`、`memory/latest`、局结束落盘稳定性
- 持续验证 prompt 只读取当前活动 run 摘要，而不是跨局数据

### 5. Memory V2

- 补全 battle enemy / room / signature 字段
- 补全 reward 的完整 replay 语义，而不只是当前 turn 提取
- 扩展跨局检索和更深入的经验聚合
- 增加 lessons / strategy extraction

## 参考文档

- [docs/memory/README.md](docs/memory/README.md)
- [docs/memory/MEMORY_DESIGN.md](docs/memory/MEMORY_DESIGN.md)
- [docs/memory/MEMORY_V1.md](docs/memory/MEMORY_V1.md)
- [docs/TODO.md](docs/TODO.md)
