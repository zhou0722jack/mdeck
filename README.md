# mdeck · 原生前端

当前分支 `codex/droiddeck-ui` 使用前一版 DroidDeck 0.6.9 移植稿的视觉设计，
以 SwiftUI 原生组件重做 mdeck 前端。主界面不使用 WebView 或网页包装层。

Steam、游戏库、商店、桌面、组件、应用、设置、更新均使用原来的 mdeck
数据和功能入口。没有对应新设计的页面、开关和按钮继续保留。

详细映射、源码检查和验证限制见
[原生前端重构说明](docs/NATIVE_FRONTEND_ZH_CN.md)。

## 源码检查（不构建）

```sh
python3 tests/host/check-native-deck.py
python3 tests/host/check-localization.py --static-only
python3 tests/host/check-jit-method.py
python3 tests/host/check-jit-network.py --static-only
python3 tests/host/check-onboarding.py --static-only
```

Xcode 工程为 `app/Madeira.xcodeproj`，应用目标为 `Madeira`。
已恢复原生 Wine/FEX/JIT 和商店依赖；本轮没有构建、链接或安装 IPA。
`dist` 中的旧 IPA 不包含本轮的原生重构。

## 视觉参考

前一版 `DroidDeckUI` 的 HTML/CSS/JavaScript 与截图保留为设计参考，
不属于当前应用资源或运行代码。浏览器预览不能代表本轮原生界面的验证结果。

参考源为 [DroidDeck 0.6.9](https://github.com/Droid-Deck/DroidDeck/tree/0.6.9)。
相关许可与资源来源见 [参考移植稿说明](app/Madeira/DroidDeckUI/NOTICE.md)。
