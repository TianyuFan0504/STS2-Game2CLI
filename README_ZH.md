# STS2-Game2CLI

`STS2-Game2CLI` 是一个把真实运行中的 Steam 版《Slay the Spire 2》接到命令行和本地 agent harness 上的适配层。

<p align="center">
  <img src="assets/example_gif.gif" alt="STS2-Game2CLI demo" width="900">
</p>

它的工作方式是：

1. 游戏内桥接插件 `STS2_Bridge` 运行在游戏进程中。
2. 插件在本机暴露 HTTP 接口 `http://localhost:15526/api/v1/singleplayer`。
3. Python CLI `sts2` 通过这个接口读取状态、执行动作。
4. `agent-harness/` 里的 `pi-agent` 和本地前端都复用同一个 `sts2` 命令。

这个项目控制的是正在运行的真实游戏，不是 headless 模拟器，也不是屏幕自动化脚本。

## 当前包含什么

- `sts2cli/`
  - Python CLI 适配层，提供 `sts2` 命令。
- `bridge/plugin/`
  - `.NET 9` 桥接插件源码。
- `bridge/install/`
  - 桥接插件安装 bundle 和安装脚本。
- `agent-harness/pi-agent/`
  - 固定版本的 `pi` runtime 和循环 runner。
- `agent-harness/frontend/`
  - 本地浏览器控制台，默认监听 `127.0.0.1:8765`。

## 环境要求

- 已安装 Steam 版《Slay the Spire 2》并且可以正常启动
- Python `>= 3.10`
- `.NET 9 SDK`
- `npm`
  - 只有在你要使用 `pi-agent` 时才需要

当前仓库里的桥接插件构建和安装脚本默认按 macOS Steam 安装路径做自动检测；如果你的游戏目录不同，需要传参或设置环境变量覆盖。

## 安装

### 1. 安装 CLI

推荐在仓库根目录执行：

```bash
python3 -m pip install -e .
```

安装后会得到 `sts2` 命令。

同时也会暴露 Python 模块入口，所以安装后 `python3 -m sts2 --help` 也可以作为兼容兜底方式使用。

如果你只是想在仓库内本地使用，也可以直接运行根目录下的 repo-local launcher：

```bash
./sts2 --help
```

前端控制服务和 `pi-agent` runner 现在也会把仓库根目录加入 `PATH`，所以即使你没有全局安装 `sts2`，agent 运行时也能把 repo 内置的 `./sts2` 当成 `sts2` 来调用。

### 2. 构建桥接插件

```bash
cd bridge/plugin
./build.sh
```

脚本会自动尝试检测游戏数据目录，并把安装用文件同步到：

```text
bridge/install/bridge_plugin/
```

如果自动检测失败，先设置 `STS2_GAME_DATA_DIR`，或者直接把目录传给脚本：

```bash
STS2_GAME_DATA_DIR="/path/to/data_sts2_macos_arm64" ./build.sh
```

或：

```bash
./build.sh "/path/to/data_sts2_macos_arm64"
```

`build.sh` 要求目标目录里至少存在：

- `sts2.dll`
- `GodotSharp.dll`
- `0Harmony.dll`

### 3. 安装 CLI 启动器

```bash
cd bridge/install
./install_cli.sh
```

这个脚本会把仓库根目录里的 repo-local launcher：

```text
<repo_root>/sts2
```

链接到默认目标：

```text
/opt/homebrew/bin/sts2
```

如果你想指定别的目标路径：

```bash
./install_cli.sh "/your/bin/sts2"
```

### 4. 安装桥接插件到游戏

```bash
cd bridge/install
./install_bridge.sh
```

默认安装目标是：

```text
~/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/MacOS/mods/STS2_Bridge/
```

如果游戏不在默认目录，直接传游戏根目录：

```bash
./install_bridge.sh "/path/to/Slay the Spire 2"
```

安装完成后，游戏目录里应该有：

```text
<game_install>/SlayTheSpire2.app/Contents/MacOS/mods/STS2_Bridge/STS2_Bridge.dll
<game_install>/SlayTheSpire2.app/Contents/MacOS/mods/STS2_Bridge/STS2_Bridge.json
```

### 5. 在游戏里启用插件

启动游戏后，确认 `STS2_Bridge` 已加载并启用。启用成功后，插件会监听：

```text
http://localhost:15526/
http://127.0.0.1:15526/
```

CLI 默认使用：

```text
http://localhost:15526/api/v1/singleplayer
```

### 6. 验证安装

```bash
sts2 --help
sts2 state
```

如果 `sts2 state` 能返回 JSON，说明 CLI 和桥接插件已经连通。

## 启动与使用

### 最短路径

1. 构建并安装 `STS2_Bridge`
2. 启动真实游戏并启用 mod
3. 在仓库根目录执行 `python3 -m pip install -e .`
4. 运行 `sts2 state`

### 从主菜单开始

当前代码已经支持从主菜单继续存档、开始新局、放弃存档和回主菜单。

示例：

```bash
sts2 state
sts2 continue-game
sts2 start-game --character IRONCLAD --ascension 0
sts2 abandon-game
sts2 return-to-main-menu
```

`start-game --character` 当前适配了这些角色名：

- `IRONCLAD`
- `SILENT`
- `DEFECT`
- `NECROBINDER`
- `REGENT`

### 在 run 中手动控制

```bash
sts2 state
sts2 choose-map 0
sts2 play-card 0 --target jaw_worm_0
sts2 end-turn
sts2 claim-reward 0
sts2 pick-card-reward 0
sts2 rest 0
sts2 event 0
sts2 repl
```

常见命令分组：

- 状态读取：`state`、`raw-state`
- 菜单动作：`continue-game`、`start-game`、`abandon-game`、`return-to-main-menu`
- 战斗：`play-card`、`use-potion`、`end-turn`
- 地图和房间：`choose-map`、`event`、`advance-dialogue`、`rest`、`proceed`
- 奖励和覆盖层：`claim-reward`、`pick-card-reward`、`skip-card-reward`、`select-card`、`confirm-selection`、`select-relic`

完整命令面可以看：

```bash
sts2 --help
```

## Agent Harness

### `pi-agent`

先安装固定版本 runtime：

```bash
bash agent-harness/pi-agent/setup_pi_agent.sh
```

然后准备根目录 `.env`：

```bash
cp .env.example .env
```

最小配置示例：

```bash
PI_PROVIDER=openrouter
PI_MODEL=auto
OPENROUTER_API_KEY=sk-or-...
PI_CODING_AGENT_DIR=/absolute/path/to/STS2-Game2CLI/.agents/pi-home
```

启动 runner：

```bash
bash agent-harness/pi-agent/run_pi_sts2_agent.sh
```

临时覆盖 provider 或 model：

```bash
bash agent-harness/pi-agent/run_pi_sts2_agent.sh --provider openai --model <tool-capable-model>
```

运行前提：

- `sts2` 命令可用
- `sts2 state` 已经能正常连到游戏
- `.env` 中的 provider / API key 已配置

日志默认写到：

```text
logs/pi-agent/<timestamp>/
logs/pi-agent/latest
```

### 本地前端控制台

启动：

```bash
bash agent-harness/frontend/start.sh
```

默认地址：

```text
http://127.0.0.1:8765
```

可选参数：

```bash
python3 agent-harness/frontend/server.py --host 127.0.0.1 --port 8765
```

前端会读取根目录 `.env`，并通过本地控制服务去拉起 `pi-agent`、查看最新游戏状态、记录 memory 数据。

## 配置项

### CLI

- `--base-url`
  - 默认 `http://localhost:15526`
- `--timeout`
  - 默认 `10.0`

示例：

```bash
sts2 --base-url http://127.0.0.1:15526 --timeout 20 state
```

### 桥接插件构建

- `STS2_GAME_DATA_DIR`
  - 当 `bridge/plugin/build.sh` 无法自动找到游戏数据目录时使用

### `pi-agent` / 前端 `.env`

- `PI_PROVIDER`
  - 默认 provider
- `PI_MODEL`
  - 默认 model
- `OPENROUTER_API_KEY`
  - 当 provider 是 `openrouter` 时需要
- `PI_CODING_AGENT_DIR`
  - `pi` 的本地工作目录；默认是 `./.agents/pi-home`
- `PI_BASE_URL`
  - 可选，自定义 provider base URL
- `PI_API_KEY_ENV`
  - 配合 `PI_BASE_URL` 使用，告诉 runner 应该从哪个环境变量取 key
- `STS2CLI_ENV_FILE`
  - 可选，覆盖 `run_pi_sts2_agent.sh` 默认读取的 `.env` 路径
- `STS2_BIN`
  - 可选，显式指定 `sts2` 可执行文件路径

当设置了 `PI_BASE_URL` 时，runner 会自动在 `PI_CODING_AGENT_DIR/models.json` 里生成 provider override。

## 常见问题

### `sts2 state` 连接失败

通常说明以下几件事之一还没满足：

- 游戏没有启动
- `STS2_Bridge` 没有安装或没有启用
- 本地接口 `localhost:15526` 还没起来

### `bridge/plugin/build.sh` 找不到游戏目录

先确认游戏已经安装，再显式传入 `STS2_GAME_DATA_DIR`：

```bash
STS2_GAME_DATA_DIR="/path/to/data_sts2_macos_arm64" ./bridge/plugin/build.sh
```

### `pi-agent` 提示 runtime 未安装

重新执行：

```bash
bash agent-harness/pi-agent/setup_pi_agent.sh
```

### 前端起不来

先单独确认这三件事：

```bash
sts2 --help
sts2 state
python3 agent-harness/frontend/server.py --help
```

## 相关文档

- [docs/INSTALL.md](docs/INSTALL.md)
- [docs/BRIDGE_PLUGIN.md](docs/BRIDGE_PLUGIN.md)
- [docs/BRIDGE_API.md](docs/BRIDGE_API.md)
- [docs/HOW_TO_DO.md](docs/HOW_TO_DO.md)
- [bridge/plugin/README.md](bridge/plugin/README.md)
- [agent-harness/pi-agent/README.md](agent-harness/pi-agent/README.md)
- [agent-harness/frontend/README.md](agent-harness/frontend/README.md)

## 致谢
本项目收到了以下项目的启发：
- [`wuhao21/sts2-cli`](https://github.com/wuhao21/sts2-cli)
- [`Gennadiyev/STS2MCP`](https://github.com/Gennadiyev/STS2MCP)
- [`HKUDS/CLI-Anything`](https://github.com/HKUDS/CLI-Anything)
