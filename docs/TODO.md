# STS2CLI TODO

## 当前状态

当前项目已经具备这些基础能力：

- 通过桥接插件控制真实 Steam 版游戏
- 通过 `sts2` CLI 暴露原子控制命令
- 通过 `pi` harness 驱动 agent 自动游玩
- 通过浏览器前端控制 agent、查看状态和日志
- Memory V1 已有实现骨架：单局短期记忆目录、事件流、摘要和 prompt 注入已经接入前端控制服务

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

### 4. Memory V1 Completion

- 校验 V1 当前实现是否完全符合文档
- 补齐 `session.json / summary.md / state_snapshot.json / events.jsonl` 字段完整性
- 验证 `run_id`、`memory/latest`、局结束落盘稳定性
- 验证 prompt 读取的是当前 run 摘要，而不是跨局数据

### 5. Memory V2

- 增加 `turns/`、`battles/`、`rewards/`、`derived/`
- 增加局结束总结
- 增加 `memory/archive/index.sqlite`
- 支持跨局检索和经验聚合

## 参考文档

- [docs/memory/README.md](/Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/docs/memory/README.md)
- [docs/memory/MEMORY_DESIGN.md](/Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/docs/memory/MEMORY_DESIGN.md)
- [docs/memory/MEMORY_V1.md](/Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/docs/memory/MEMORY_V1.md)
- [docs/TODO.md](/Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/docs/TODO.md)
