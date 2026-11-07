# Steam 全局设置、预览与客户端启动

本次核对 DroidDeck 提交 `aba55031c331cd0991c3d36788fb903a3ca30e78`：

- `ui/SteamHome.kt` 的 `LiftHero` 将主页启动与 Steam 会话设置放在一起。
- `ui/GameDetail.kt` 的 `GameBackdrop`、`AboutTab` 与 `LaunchTab` 展示游戏背景、资料及启动控制。
- `session/SessionService.kt` 默认使用 Steam 会话；桌面模式才导出 `BL_STEAM_UI=desktop`。冷启动将 Steam URL 传给会话脚本；已有会话通过 `steam-game` 请求文件排队交给客户端。游戏身份采用 `steam://rungameid/<App ID>`。
- `tools/linuxfs/overlay/usr/local/bin/droiddeck-session` 第 1407 行默认传入 `-gamepadui`，桌面模式才清除此参数；第 1513 行用 `steam://rungameid/<App ID>` 请求客户端启动游戏。mdeck 同样使用 `-gamepadui` 开启大屏模式，游戏请求使用 Windows Steam 的 `-applaunch <App ID>` 接口。
- `frontend/Library.kt` 负责本地游戏与封面资料。Android 的 Linux Steam 会话不能直接搬到 iOS/Wine。

对应源文件可在 [上游固定提交](https://github.com/Droid-Deck/DroidDeck/tree/aba55031c331cd0991c3d36788fb903a3ca30e78/app/src/main/java/com/droiddeck/launcher) 查阅。原有 GPL 声明和 DroidDeck 素材归属保留。

## mdeck 的实现

主页“启动 Steam”下方提供“Steam 设置”。设置包含全局大屏模式开关、客户端附加参数、账户、游戏语言、云存档、局域网下载，以及已有全局图形、显示、内存和输入设置入口。原设置列表及搜索页移除“Steam 与 Dock”。默认开启大屏模式；兼容参数始终补齐。设置作用于下次会话，不更改正在运行的客户端。

组件准备只检查 Wine Mono、Visual C++、Wine Gecko，既有组件复用，缺失项并行下载，不再准备 Madeira Dock 客户端。

库内已安装游戏先进入原生预览页：封面、简介、开发商、发行商、可横向浏览并放大的截图、游玩时长、游戏设置和启动按钮。未安装游戏在原下载页面也展示预览，保留安装/暂停/恢复控制。公开商店资料通过 Valve HTTPS 接口加载，优先使用 URL 缓存；失败可重试，不影响已安装游戏启动。资料仅用于展示，不据此判断授权。

本地发现同时读取交互客户端和旧下载目录的 appmanifest 及两个位置的 libraryfolders.vdf。启动前将已有游戏库合并登记到交互客户端，保留既有元数据；不下载 Dock，也不启动其固定版本客户端。

游戏启动经过真实安装状态与下载状态检查、现有云存档流程和三组件准备，最终在 `C:\Program Files\Steam Client\Steam.exe` 上使用 `-applaunch <App ID>`（Windows Steam 对应的 App ID 启动接口），并带上全局大屏/兼容参数和游戏自己的附加参数。已有单独选择“游戏程序”的免 Steam 启动方式继续保留。

首次缺少 Steam 时仍由同一 Wine 会话中的安装控制器安装；原生子进程参数规则同时携带目标 App ID，交接后启动该游戏。游戏显示、触控和性能设置从原游戏配置复制，临时客户端路线不覆盖游戏记录或将 -applaunch 写进全局设置。

## 验证边界

主机测试覆盖三个组件、安装到客户端的连续加载状态机、真实目录与 VDF 注册、全局模式切换、游戏请求及后续重启参数隔离、公开资料解码和 iOS SDK 原生预览/设置类型检查。

IPA 构建与上述源码验证分别验收。尚需 iPad 验证：大屏模式实际渲染、Steam 更新后是否保留目标游戏请求、真实账户游戏授权和游戏画面、具体游戏首次依赖安装。沿用每次 App 运行只初始化一次 Wine 的限制；没有增加后台保活 Steam 或退出会话后再次初始化 Wine 的能力。
