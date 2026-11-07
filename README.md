# mdeck · 原生前端

当前分支 `codex/droiddeck-ui` 使用前一版 DroidDeck 0.6.9 移植稿的视觉设计，
以 SwiftUI 原生组件重做 mdeck 前端。主界面不使用 WebView 或网页包装层。

Steam、游戏库、商店、桌面、组件、应用、设置、更新均使用原来的 mdeck
数据和功能入口。没有对应新设计的页面、开关和按钮继续保留。

本轮加入 DroidDeck 原版启动动画。首次打开只选择“脚本 JIT / 内置 JIT”，
播放动画后进入主界面；点击“启动 Steam”时，统一检查 Wine Mono、Visual C++、Wine Gecko 和 Madeira Dock，
并行下载缺失组件，全部就绪后自动进入原有 JIT 和 Steam 启动流程。
Steam 启动加载层使用 DroidDeck 原生变形标志、倾斜封面墙和三段进度，贯穿组件准备、启动与等待首帧；
只有目标客户端窗口收到可见图像后才自动关闭，桌面和控制台帧不会提前结束加载。
JIT 方式已选择后，进入 App 即请求/等待该方式；就绪时立即探测一次，之后前台每 5 秒使用独立 16 KiB 缓冲区执行并回收。
启动 Wine/Steam 前停止定时器并等待正在执行的一轮回收，主 JIT 池仍按原启动流程分配。
Steam 首页只保留“启动 Steam”；原来的多页新手引导已移除。
流程说明见 [首次启动与组件准备](docs/STARTUP_ZH_CN.md)。

详细映射、源码检查和验证限制见
[原生前端重构说明](docs/NATIVE_FRONTEND_ZH_CN.md)。

## 源码检查（不构建）

```sh
python3 tests/host/check-native-deck.py
python3 tests/host/check-localization.py --static-only
python3 tests/host/check-jit-method.py
python3 tests/host/check-jit-network.py --static-only
python3 tests/host/check-deck-startup.py --static-only
```

Xcode 工程为 `app/Madeira.xcodeproj`，应用目标为 `Madeira`。
本轮应用与 JIT 助手的构建号为 **13**，IPA 通过 GitHub Actions 的 `Build IPA` 工作流生成。
此前的 `dist/native-build8/Madeira.ipa` 包含前一轮原生界面，不包含本次启动流程。
Build 10 改为双击启动动画跳过，并直接运行 Steam 安装器，避免先启动 explorer 桌面。
Build 11 加入受“扩展日志”控制的运行库调用来源诊断，以及异常处理的线程状态检查。
它用于继续定位 Steam 初始化故障，不代表安装器已经修复。
当前源码另已修正子按钮查询顶层窗口时对无客户端对象桌面的识别，加入 Noto Sans SC 中文字体与旧环境字体回退迁移，
并将“附加代码页”设为默认开启（显式设为 0 仍可关闭）。这些改动从 Build 12 起打包，尚未在 iPad 上验收。
针对性检查：`python3 tests/host/check-desktop-button-click.py`、
`python3 tests/host/check-chinese-fonts.py`、`python3 tests/host/check-nls-extra-switch.py`。
Build 13 加入点击 Steam 时四组件并行准备、持续到目标首帧的 DroidDeck 原生加载动画，
以及进入 App 请求 JIT、前台每五秒独立 16 KiB 探测并在 Wine 启动前等待回收的流程。
新启动流程的模型行为测试与 iOS 视图类型检查可运行
`DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer python3 tests/host/check-deck-startup.py --typecheck-ios`。

## 视觉参考

前一版 `DroidDeckUI` 的 HTML/CSS/JavaScript 与截图保留为设计参考，
不属于当前应用资源或运行代码。浏览器预览不能代表本轮原生界面的验证结果。

参考源为 [DroidDeck 0.6.9](https://github.com/Droid-Deck/DroidDeck/tree/0.6.9)。
相关许可与资源来源见 [参考移植稿说明](app/Madeira/DroidDeckUI/NOTICE.md)。
