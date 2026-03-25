# INSTALL

这份文档把 `STS2CLI` 的安装流程收敛成项目内的固定步骤。

## 目录约定

项目内固定安装资源目录：

```text
STS2CLI/
  bridge/
    plugin/
      <plugin source>
    install/
      STS2_Bridge.dll
      STS2_Bridge.json
      install_bridge.sh
      install_cli.sh
```

## 1. 构建桥接插件

```bash
cd /Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/bridge/plugin
./build.sh
```

构建完成后，会自动把安装用文件同步到：

```text
STS2CLI/bridge/install/bridge_plugin/
```

## 2. 安装桥接插件到游戏

```bash
cd /Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/bridge/install
./install_bridge.sh
```

默认安装到：

```text
~/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/MacOS/mods/STS2_Bridge/
```

如果你的游戏目录不一样，也可以手动传：

```bash
./install_bridge.sh "/path/to/Slay the Spire 2"
```

## 3. 安装 CLI 命令

```bash
cd /Users/tianyufan/Desktop/workspace/Slay_the_Spire/STS2CLI/bridge/install
./install_cli.sh
```

默认会把 `sts2` 命令链接到：

```text
/opt/homebrew/bin/sts2
```

实际链接源是仓库根目录下的 repo-local launcher：

```text
STS2CLI/sts2
```

如果你不想创建全局链接，也可以直接在仓库根目录运行：

```bash
./sts2 --help
```

前端控制服务和 `pi-agent` runner 也会自动把仓库根目录加入 `PATH`，所以 agent 运行时可以直接把这个 repo-local launcher 当成 `sts2` 使用。

如果你要改目标路径：

```bash
./install_cli.sh "/your/bin/sts2"
```

## 4. 验证

```bash
sts2 --help
python3 -m sts2 --help
sts2 state
```

## 5. 使用前提

- 真实 Steam 版游戏已经启动
- 游戏里已经加载并启用 `STS2_Bridge`
- 你已经手动开始一局单人 run
