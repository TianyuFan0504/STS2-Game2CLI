# Bridge Plugin

这份文档总结 `STS2CLI` 运行所需的游戏桥接插件信息，避免再依赖外部仓库文档。

## 作用

桥接插件运行在真实 Steam 版《Slay the Spire 2》游戏进程内部，负责：

- 读取当前游戏状态
- 执行出牌、结束回合、选点、领奖励等动作
- 在本机暴露一个本地 HTTP 接口供 `STS2CLI` 调用

`STS2CLI` 本身不直接操作游戏窗口，也不做屏幕自动化。

## 当前已知能力

单人模式支持：

- 战斗：出牌、用药水、结束回合、战斗中卡牌选择
- 奖励：领取奖励、选卡、跳过卡牌奖励
- 地图：路径选择
- 休息点：选择休息、锻造等选项
- 事件与远古事件：推进对话、选择选项
- 商店：购买卡牌、遗物、药水
- 覆盖层：卡牌选择、遗物选择、宝箱遗物领取

当前限制：

- 只能接管已经开始的单人 run
- 还没有从主菜单直接自动开始新 run 的接口

## 安装到游戏

游戏目录下需要存在：

- `mods/STS2_Bridge.dll`
- `mods/STS2_Bridge.json`

也就是：

```text
<game_install>/mods/STS2_Bridge.dll
<game_install>/mods/STS2_Bridge.json
```

进入游戏后，还需要在设置中启用这个桥接插件。

启用成功后，插件会自动在本机打开接口：

```text
http://localhost:15526/api/v1/singleplayer
```

## 如果你自己编译桥接插件

已知构建产物和安装映射如下：

```text
bridge/plugin/out/STS2_Bridge/STS2_Bridge.dll  ->  <game_install>/mods/STS2_Bridge.dll
bridge/plugin/bridge_manifest.json             ->  <game_install>/mods/STS2_Bridge.json
```

构建插件需要 .NET 9 SDK。

## 运行 `STS2CLI` 前的最低要求

1. 真实 Steam 图形版游戏已经启动
2. 桥接插件已经安装并启用
3. 你已经手动开始一局单人 run

满足这三条之后，`STS2CLI` 才能工作。
