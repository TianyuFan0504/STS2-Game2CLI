# Memory Docs

这个目录主要放 memory 设计文档。

其中 V1 已经开始在前端控制服务里落地实现，运行时会按设计生成单局目录。

## 文件说明

- `MEMORY_DESIGN.md`
  - 完整设计稿
  - 包含短期记忆、长期记忆、存储分层、索引、生命周期、注入策略

- `MEMORY_V1.md`
  - 第一阶段最小实现范围
  - 明确先做哪些文件、哪些字段、哪些触发时机

- `MEMORY_V2.md`
  - 第二阶段跨局索引范围
  - 明确单局派生数据、SQLite 索引层和跨局检索边界

- `MEMORY_V1_TODO.md`
  - V1 实现待办
  - 聚焦单局短期记忆

- `MEMORY_V2_TODO.md`
  - V2 实现待办
  - 聚焦跨局索引和检索

## 当前原则

- 先设计，后实现
- 先单局短期记忆，后跨局长期记忆
- 运行期数据留在 `memory/runs/<run_id>/`，设计文档统一放在 `docs/memory/`
- 先 `memory/runs/<run_id>/` 单局目录，后 `memory/archive/index.sqlite`
- 当前已开始实现 V1
- V2 仍然停留在设计阶段
