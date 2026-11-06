# mdeck · 原生前端

当前分支 `codex/droiddeck-ui` 使用前一版 DroidDeck 0.6.9 移植稿的视觉设计，
以 SwiftUI 原生组件重做 mdeck 前端。主界面不使用 WebView 或网页包装层。

Steam、游戏库、商店、桌面、组件、应用、设置、更新均使用原来的 mdeck
数据和功能入口。没有对应新设计的页面、开关和按钮继续保留。

本轮加入 DroidDeck 原版启动动画。首次打开只选择“脚本 JIT / 内置 JIT”，
随后自动准备 Wine Mono、Visual C++、Wine Gecko 和 Madeira Dock 客户端组件。
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
本轮应用与 JIT 助手的构建号为 **10**，IPA 通过 GitHub Actions 的 `Build IPA` 工作流生成。
此前的 `dist/native-build8/Madeira.ipa` 包含前一轮原生界面，不包含本次启动流程。
Build 10 改为双击启动动画跳过，并直接运行 Steam 安装器，避免先启动 explorer 桌面。
新启动流程的模型行为测试与 iOS 视图类型检查可运行
`DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer python3 tests/host/check-deck-startup.py --typecheck-ios`。

## 视觉参考

前一版 `DroidDeckUI` 的 HTML/CSS/JavaScript 与截图保留为设计参考，
不属于当前应用资源或运行代码。浏览器预览不能代表本轮原生界面的验证结果。

参考源为 [DroidDeck 0.6.9](https://github.com/Droid-Deck/DroidDeck/tree/0.6.9)。
相关许可与资源来源见 [参考移植稿说明](app/Madeira/DroidDeckUI/NOTICE.md)。
