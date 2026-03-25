# HOW TO DO

这份文档说明如何使用 `STS2CLI/` 来控制 **Steam 图形版正在运行的真实 Slay the Spire 2**。

## 先回答你的问题

**要，你必须打开游戏。**

当前这版 `STS2CLI` 不是 headless 模拟器，也不会自己启动一局新 run。它依赖：

1. Steam 图形版游戏已经启动
2. 游戏桥接插件已经安装并启用
3. 你已经在游戏里手动开始了一局单人 run

然后 `STS2CLI` 才能接管这局游戏。

## Step 1: 确认桥接插件已安装

`STS2CLI` 本身不直接控制游戏窗口，它是通过游戏进程内的桥接插件暴露出来的本地 HTTP 接口控制真实游戏。

桥接插件的安装和接口说明已经整理到本项目内：

- [docs/BRIDGE_PLUGIN.md](/Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/docs/BRIDGE_PLUGIN.md)
- [docs/BRIDGE_API.md](/Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/docs/BRIDGE_API.md)

你至少需要保证这件事成立：

- 游戏的 `<game_install>/mods/` 里有：
  - `STS2_Bridge.dll`
  - `STS2_Bridge.json`
- 进入游戏后，这个 mod 已经在设置里启用

如果你还没有这两个文件，可以直接在本项目里构建桥接插件源码：

- [bridge/plugin/README.md](/Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/bridge/plugin/README.md)

启用成功后，游戏会在本机打开：

`http://localhost:15526/api/v1/singleplayer`

## Step 2: 打开 Steam 图形版游戏

正常从 Steam 启动 `Slay the Spire 2`。

不要只运行 `STS2CLI`。  
如果真实游戏没开，下面的命令会报错：

```bash
Cannot connect to the game bridge API. Is the game running with the bridge mod enabled?
```

## Step 3: 手动开始一局单人游戏

这是当前版本最重要的限制。

`STS2CLI` 目前 **不能从主菜单自动 `start_run`**。  
所以你需要在真实游戏里手动完成这些动作：

1. 进入主菜单
2. 开始单人游戏
3. 选角色
4. 进入第一层地图或第一场战斗

如果你还停留在主菜单，`STS2CLI` 只能读到 `menu` 状态，不能自动玩。

## Step 4: 进入 `STS2CLI` 目录

```bash
cd /Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI
```

## Step 5: 先测试连接

先读一次当前状态：

```bash
sts2 state
```

可能出现三种情况：

- 返回 `menu`
  说明游戏开着，但你还没开始 run
- 返回 `combat_play` / `map_select` / `event_choice` 等
  说明可以开始控制
- 连接失败
  说明游戏没开，或者桥接插件没启用，或者本地接口没有起来

## Step 6: 手动控制一两个命令

示例：

```bash
sts2 state
sts2 choose-map 0
sts2 play-card 0 --target jaw_worm_0
sts2 end-turn
sts2 claim-reward 0
sts2 pick-card-reward 0
sts2 rest 0
sts2 event 0
```

说明：

- `choose-map 0` 里的编号来自当前 `state` 输出里的 `choices`
- `play-card 0` 里的编号来自 `hand`
- `--target` 需要传敌人的 `entity_id`

## Step 7: 使用交互式命令行或外部 harness

当前 `sts2` 只保留原子控制命令，不再内置自动 agent。

```bash
sts2 repl
```

如果你想让模型自动玩，使用项目里的外部 harness：

- `pi` 方案：
  [agent-harness/pi-agent/README.md](/Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/agent-harness/pi-agent/README.md)
- 交互式 shell：
  `sts2 repl`

## Step 8: 遇到问题时怎么排查

先执行：

```bash
sts2 state
```

重点看这几类结果：

- `menu`
  说明还没开始 run
- `overlay`
  说明有未适配的覆盖层，可能需要你在游戏里手动点一下
- 连接失败
  说明游戏或 mod 没在线

## 当前边界

当前 `STS2CLI` 已经能做：

- 接管真实 Steam 图形版单人 run
- 用 CLI 命令控制真实游戏

当前还不能做：

- 从主菜单自动开始一局新 run
- 不开游戏直接玩
- 替代 `sts2-cli` 的 headless 模式

## 推荐的最短使用路径

1. 安装并启用桥接插件
2. 打开真实游戏
3. 手动开一局单人 run
4. 在 `STS2CLI/` 里运行 `sts2 state`
5. 运行 `sts2 repl` 或启动 `pi-agent`
