# DroidDeck 界面移植分支

> 本文记录前一版网页视觉参考稿。当前应用已按用户要求改成原生 SwiftUI，
> 不再加载此网页界面。请以 [原生重构说明](NATIVE_FRONTEND_ZH_CN.md) 为准。

分支：`codex/droiddeck-ui`。

参考版本固定为 DroidDeck **0.6.9**，提交
`0a07926ef3477c90db911d169904137cfc5e2505`。
参考仓库：[Droid-Deck/DroidDeck](https://github.com/Droid-Deck/DroidDeck/tree/0.6.9)。

## 运行内容

这个分支将 mdeck 的应用入口换成独立的本地界面。SwiftUI 提供应用壳，
WKWebView 从应用资源加载 `DroidDeckUI/index.html`。界面代码不访问网络，
也没有 JavaScript 到原生的服务调用通道。Xcode 应用目标仅包含
`MadeiraApp.swift` 和 `DroidDeckShell.swift`，不再编译或链接 Wine、FEX、
StikJIT、Steam 下载器以及原来的商店服务。

原有后端源码仍在 Git 仓库中，供其他分支继续使用，但不属于此分支的应用
目标。系统权限和后台服务初始化也已从本分支的应用入口移除。

界面中的游戏、容量、成就、账号状态、下载和会话是固定样例或本地状态。
登录字段不提交、不保存密码；下载按钮只演示进度；卸载和清理不触碰磁盘。
主题、布局、动画和选项保存在界面自身的本地存储中。

## 页面覆盖

| 主入口 | 当前包含的界面和交互 |
| --- | --- |
| Steam | 封面墙、Logo、游玩按钮、上拉会话设置、启动动画与加载状态 |
| 游戏库 | 来源筛选、搜索、排序、收藏、卡片大小、列表/方形/竖版布局、添加入口 |
| 游戏详情 | 横幅、游戏 Logo、来源与安装状态、胶囊操作栏、关于/成就/启动/存档/安装页签 |
| 游戏商店 | Steam/GOG/Epic/Amazon/Xbox/itch.io/Battle.net/Game Jolt 切换、商品架、登录与下载界面 |
| 桌面 | 桌面启动、Flathub 应用、模拟器图标和详情、文件与 ROM 选择界面 |
| 组件 | 配置档案、GPU 驱动、Proton/DXVK/VKD3D/FEX、Windows 组件、环境变量编辑 |
| 应用 | 应用网格、搜索、菜单 |
| 配置 | 概览、手柄、启动器、存储、诊断、智能眼镜六个页签 |
| 存储 | 容量分布、分类详情、清理确认、安装位置 |
| 运行界面 | 加载 Logo、暂停/继续/停止、右侧设置抽屉、触控板、键盘与屏幕手柄 |
| 其他面板 | 帧生成、画面效果、按键映射、触摸手势、眼镜/空间校准、开机动画、通知/聊天/截图/统计 |

Android 的系统授权弹窗、真实 Steam/KDE 窗口和下载回包不属于本地界面。
这类位置保留可到达的界面状态，不执行对应系统或后端操作。

## 动画来源

`motion.js` 与 `theme.js` 参照固定版本的以下实现：

- `FrontEndScreen.kt`：`(0.2, 0.8, 0.2, 1)` 缓动、450 ms 入场、60 ms 分批延迟。
- `SharedMotion.kt`：领先边/拖尾边的滑动选中框，40 ms 延迟，700/360 弹簧刚度，
  以及 150 ms 收缩与 300 ms 弧线飞行。
- `LiftSheet.kt`：上拉面板与拖动回弹，0.7 阻尼和 380 刚度。
- `PageFlood.kt`、`LaunchFlood.kt`：卡片展开、按钮铺满过渡的对应效果。
- `Throbber.kt`：1,900 ms Logo 周期、方形到圆弧的变形、转动与中心球缩放。
- `ThemeColors.kt`：HSV 调色、最低亮度和渐变对比度调整。
- `SteamHome.kt`：倾斜封面墙及 75 秒缓慢移动。

Web 动画与 Compose 的布局/合成系统不同。现已对主要页面作浏览器检查，
但未完成原 APK 全部页面、所有主题、每一帧的差异比对，不能据此宣称像素级
或所有动画完全一致。卡片展开、设置面板结构、部分复杂弹窗仍有还原差异。
目前属于可交互移植稿，后续应以真机或模拟器对照继续验收。

## 检查与预览

不构建即可执行：

```sh
node tests/host/check-droiddeck-ui.js
python3 -m http.server 8765 --bind 127.0.0.1 --directory app/Madeira/DroidDeckUI
```

浏览器打开 `http://127.0.0.1:8765/`。检查覆盖主导航与二级面板渲染、资源、
后端隔离、排序、收藏和渐变颜色约束。它不替代 WebKit 真机或 APK 视觉验收。

2026-11-06 本轮验证记录：

- 8 个主入口和 46 个二级路由通过 JavaScript 渲染检查。
- 浏览器检查了游戏库、游戏详情、配置、存储、主题、会话设置及嵌套选项。
- 390×844 竖屏未出现页面横向溢出；1180×820 横屏使用 92px 侧栏。
- 渐变主题刷新后保留；本轮检查没有捕获到 JavaScript 错误。
- 游戏库中的封面资源检查无加载失败；新增资源有文件大小和 SHA-256 校验。
- 截图记录位于 `docs/droiddeck-preview/`，是本地浏览器截图，非 iOS 实机结果。

按用户要求，本次没有运行 Xcode、Swift 编译、APK/IPA 构建或安装。

## 文件分布与来源

- `app/Madeira/DroidDeckUI/`：本地 HTML、CSS、JavaScript、字体、图标和图片。
- `tools/droiddeck/import-ui.py`：从固定版本提取双语文案、设置行目录与 Logo 路径；
  输出 apply_patch 补丁，不直接改写目标文件。
- `docs/droiddeck-source-manifest.json`：参考版本的 110 个 UI 文件及其 SHA-256。
  该数字是参考文件清单，并不表示 110 个文件均已逐行移植或完成视觉验收。
- `docs/droiddeck-assets.json`：所有随包资源的大小与 SHA-256。
- `app/Madeira/DroidDeckUI/NOTICE.md`：资源、字体与代码的许可和来源说明。

原先 Steam 安装器与外部 JIT 修改保留在 `codex/pr-build-steam-installer`；
本分支不会把那些后端接入新界面。旧 build 6 IPA 也不是此界面移植稿。
