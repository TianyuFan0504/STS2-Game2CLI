# Frontend

本目录提供一个本地浏览器控制台，用来控制 `STS2CLI` 的 `pi-agent`。

## 启动

```bash
bash /Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/agent-harness/frontend/start.sh
```

默认地址：

```text
http://127.0.0.1:8765
```

## 功能

- 一键启动 agent
- 单步、自动、全自动
- 暂停、继续、停止
- 实时查看思考文本、assistant 输出、工具调用
- 查看当前游戏状态
- 手动发送 `sts2` 命令
- 按 Memory V1 方案为每局写入 `memory/runs/<run_id>/`

当前 V1 目录结构：

```text
memory/runs/<run_id>/
├── memory/
│   └── summary.md
└── data/
    ├── session.json
    ├── state_snapshot.json
    ├── ledger.jsonl
    ├── events.jsonl
    ├── agent_events.jsonl
    ├── runtime_prompt.md
    └── iterations/
        └── <iteration>/
            ├── pi.raw.jsonl
            └── pi.log
```

- `ledger.jsonl` 是单局主记录
- `events.jsonl` / `agent_events.jsonl` 是从 ledger 派生出来的视图

## 说明

- 前端静态文件在 `agent-harness/frontend/static/`
- 后端控制服务在 `agent-harness/frontend/server.py`
- 前端不直接接游戏，而是调用本地控制服务
