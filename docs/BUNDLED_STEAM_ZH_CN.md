# 内置 Steam 安装程序

游戏库顶部“桌面”旁增加“Steam”入口，普通布局和可缩放网格均可使用。

1. 使用外部 JIT 脚本模式时，先在 StikDebug 中运行 Madeira 的脚本。
2. 回到 Madeira，打开“Steam”，点击“运行 Steam 安装程序”。应用通过现有
   JIT 和 Wine 启动流程打开 Windows 安装界面。
3. 保留安装器建议的 `C:\Program Files\Steam Client` 目录，联网完成安装。
4. 结束当前 Wine 会话后，回到同一入口点击“启动 Steam”。若 Madeira 提示
   本次运行只能启动一个会话，先完全关闭并重新打开 Madeira，再重新启用 JIT。

“启动 Steam”只有在该目录中存在 `steam.exe` 时才可用。修改安装目录后，
可以使用游戏库的“+”手动添加实际的 `steam.exe`，默认按钮不会扫描其他目录。
安装器自身自动打开客户端时，可以继续使用当前会话。

## 内置资源

- 来源：[Valve 官方 Steam 下载页](https://store.steampowered.com/about/)。
- 下载地址：`https://cdn.fastly.steamstatic.com/client/installer/SteamSetup.exe`
- 下载日期：2026-11-06。
- 仓库路径：`app/Madeira/BundledInstallers/SteamSetup.exe`。
- 大小：2,380,800 字节。
- 格式：Windows PE32 / Intel i386，NSIS 安装程序。
- SHA-256：`7d3654531c32d941b8cae81c4137fc542172bfa9635f169cb392f245a0a12bcb`。

Xcode 将 `BundledInstallers` 目录作为文件夹资源复制进应用。启动安装器前，
应用校验上述散列，然后将它写入 Wine C 盘的
`Madeira/Installers/SteamSetup.exe`，因此无需用户再手动导入 EXE。
更新二进制时需要同步更新 `SteamClient.installerSHA256`。

这是 Valve 的联网安装引导程序，不包含完整 Steam 客户端或游戏。客户端与
安装器继续使用现有 Wine 桌面、Windows 服务以及 Steam 的推荐内存配置。
Steam 更新下载的组件版本由 Valve 决定，内置安装器不保证最新客户端在此设备兼容。

## 与 Madeira Dock 的关系

独立客户端安装到 `Program Files/Steam Client`；Madeira Dock 的固定版本组件
仍位于其现有目录，不用它们启动交互式客户端，也不主动更新或覆盖它们。
安装时勿手动改为 Dock 的目录。两个入口仍共用同一个 Wine 前缀和注册表，
安装器或 Steam 客户端可能修改 Steam 注册表信息；这不是完整的前缀隔离。

## 首轮实机结果与修正

build 6 已完成构建和 IPA 内容校验。2026-11-06 的 iPadOS 27 实机日志
`SteamSetup.exe-2026-11-06_20-24-49.txt` 显示：JIT 内存准备完成，调试器正常
脱离，Wine 桌面启动；随后通用服务启动脚本的 `cmd.exe` 以代码 1 退出，
未见创建 `SteamSetup.exe` 的记录。日志不能确定脚本退出的更深层原因。

修正后，安装器由 Wine 桌面直接创建，不再经过通用服务启动脚本；build 6
保存的安装器卡片在再次启动时也会使用该方式。客户端启动方式保持原样。
这解决了已定位的启动路径问题，安装器界面、后续安装及客户端仍待实机验证。
