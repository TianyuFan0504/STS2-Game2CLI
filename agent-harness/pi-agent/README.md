# Pi Agent

这个目录把已发布的 `pi` CLI 包当成外部 harness 来用，不依赖 `pi-mono` 源码入口。

## 组成

- `run_pi_sts2_agent.sh`
  - 主循环。反复调用本地安装的 `pi` CLI，每轮都让模型自己生成 `sts2 ...` 命令。
- `setup_pi_agent.sh`
  - 在 `agent-harness/pi-agent/runtime/` 里安装固定版本的 `@mariozechner/pi-coding-agent`。
- `setup_pi_mono.sh`
  - 兼容旧入口，内部会转调 `setup_pi_agent.sh`。
- `base-prompt.md`
  - agent 的共享初始 prompt 主体，方便直接改文案。
- `append-system-prompt.md`
  - 运行时追加给 pi 的系统提示，限制它只做游戏控制。
- `../start_pi_game_agent.command`
  - macOS 双击启动入口。
- `../skills/`
  - 本仓库内的本地 skills 目录，runner 会默认把整个目录作为 skill 加载路径。

## 前提

- 先安装 `pi` runtime：

```bash
bash /Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/agent-harness/pi-agent/setup_pi_agent.sh
```

- 真实游戏已经启动，桥接插件已经加载。
- `sts2 state` 正常。
- 准备好 `STS2CLI/.env`
  - 可参考：[.env.example](/Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/.env.example)
  - runner 会自动加载 `STS2CLI/.env`

推荐的最小 `.env`：

```bash
PI_PROVIDER=openrouter
PI_MODEL=auto
OPENROUTER_API_KEY=sk-or-...
PI_CODING_AGENT_DIR=/Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/.agents/pi-home
```

如果后面你要切到自定义 OpenRouter 兼容 URL，再加：

```bash
PI_BASE_URL=https://your-proxy.example.com/v1
PI_API_KEY_ENV=OPENROUTER_API_KEY
```

这样 runner 会自动在 `PI_CODING_AGENT_DIR/models.json` 里生成 provider override。

## 启动

双击：

- `STS2CLI/start_pi_game_agent.command`

或者在当前终端运行：

```bash
bash /Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/agent-harness/pi-agent/run_pi_sts2_agent.sh
```

如果你想临时覆盖 `.env` 里的 provider / model：

```bash
bash /Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/agent-harness/pi-agent/run_pi_sts2_agent.sh --provider openai --model <tool-capable-model>
```

## 停止

- 在 agent 所在终端里按 `Ctrl+C`
- 或直接关闭那个 Terminal 窗口

## 日志

每次启动都会生成一个新目录：

- `STS2CLI/logs/pi-agent/<timestamp>/`

常用文件：

- `runner.log`
- `runtime_prompt.md`
- `iterations/*/pi.log`
- `iterations/*/pi.raw.jsonl`
- `PI_CODING_AGENT_DIR/models.json`（当你设置了 `PI_BASE_URL` 时自动生成）

最近一次运行还会有一个软链接：

- `STS2CLI/logs/pi-agent/latest`

## 启动细节

runner 不通过 `npx` 临时下载，也不再走 `pi-mono` 的源码入口。

它直接调用：

- `agent-harness/pi-agent/runtime/node_modules/.bin/pi`
- 固定版本见 `agent-harness/pi-agent/runtime/package.json`
- 初始 prompt 主体见 `agent-harness/pi-agent/base-prompt.md`
- 系统层追加规则见 `agent-harness/pi-agent/append-system-prompt.md`

这样可以在项目内固定 `pi` 版本，同时保留当前 `STS2CLI/` 工作目录、skills 目录路径和日志布局。

`sts2` 的解析顺序现在是：

1. 显式设置的 `STS2_BIN`
2. 仓库根目录下的 repo-local `STS2CLI/sts2`
3. 当前 `PATH` 里的 `sts2`

同时 runner 会把仓库根目录加入 `PATH`，所以默认情况下不需要先手工全局安装 `sts2`，repo 内置 launcher 也能被 agent 直接调用。

runner 还会把 `pi` 的 `json` 事件流转成可读日志：

- 终端里实时显示文本输出和工具调用
- `pi.log` 保存可读摘要
- `pi.raw.jsonl` 保存原始事件流，便于后续排查
