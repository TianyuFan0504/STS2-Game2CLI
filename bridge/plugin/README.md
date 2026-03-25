# STS2 Bridge Plugin

这是 `STS2CLI` 自带的桥接插件源码副本，用于把真实 Steam 版《Slay the Spire 2》暴露成一个本地 HTTP 可控接口。

## 作用

桥接插件运行在游戏进程内部，负责：

- 读取当前游戏状态
- 在主线程执行游戏动作
- 打开本地接口 `http://localhost:15526/api/v1/singleplayer`

`STS2CLI` 的命令行和 agent 都是通过这个本地接口控制真实游戏。

## 当前能力

- 战斗：出牌、药水、结束回合、战斗内选卡
- 地图：选点
- 奖励：领奖励、选卡、跳过
- 房间：休息点、事件、商店、宝箱
- 覆盖层：卡牌选择、遗物选择

当前限制：

- 只能接管已经开始的 run
- 还没有主菜单自动开局接口

## 构建

需要：

- .NET 9 SDK
- 本地已安装 Steam 版《Slay the Spire 2》

在 macOS 上：

```bash
cd /Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/bridge_plugin
chmod +x build.sh
./build.sh
```

如果自动检测失败，可以手动传游戏数据目录：

```bash
./build.sh "/Users/your_name/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/Resources/data_sts2_macos_arm64"
```

## 安装

构建成功后，把下面两个文件放进游戏安装目录的 `mods/` 里：

```text
out/STS2_Bridge/STS2_Bridge.dll
bridge_manifest.json -> STS2_Bridge.json
```

也就是：

```text
<game_install>/mods/STS2_Bridge.dll
<game_install>/mods/STS2_Bridge.json
```

之后启动游戏，在设置里启用这个桥接插件。
