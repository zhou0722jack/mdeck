# mdeck · DroidDeck UI

本分支 `codex/droiddeck-ui` 将 DroidDeck 0.6.9 的启动器界面移植到 mdeck。

当前为可交互的界面移植稿：Steam 首页、游戏库与详情、商店、桌面、组件、
配置、更新和会话面板均通过本地状态驱动。按钮不连接真实后端。

详细范围、动画来源、当前还原差异和检查方式见
[界面移植说明](docs/DROIDDECK_UI_ZH_CN.md)。

## 本地预览

```sh
node tests/host/check-droiddeck-ui.js
python3 -m http.server 8765 --bind 127.0.0.1 --directory app/Madeira/DroidDeckUI
```

打开 `http://127.0.0.1:8765/`。横屏使用侧栏，竖屏使用底栏。
支持触摸、鼠标、键盘方向键与手柄导航；Esc/B 返回。

## iOS 工程

Xcode 工程仍是 `app/Madeira.xcodeproj`，应用目标 `Madeira`。
该分支仅包含 SwiftUI/WKWebView 界面壳与随包网页资源，没有原生运行时依赖。
应用标识为 `com.zhou0722jack.mdeck.droiddeckui`，与现有 Madeira 安装区分。

按用户要求，尚未构建或安装本分支的 IPA。旧 `dist` 里的 IPA 不包含新界面。
原有运行时和 Steam/JIT 改动请使用 `codex/pr-build-steam-installer` 分支。

## 来源和许可

参考：[DroidDeck 0.6.9](https://github.com/Droid-Deck/DroidDeck/tree/0.6.9)，
固定提交 `0a07926ef3477c90db911d169904137cfc5e2505`。
移植代码适用 GPL-3.0，详情见 [资源与许可说明](app/Madeira/DroidDeckUI/NOTICE.md)。
