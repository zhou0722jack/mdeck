# DroidDeck 动画分析及 Build 14 实现范围

对照版本：`18c7d56409de4cf3b63b1b09e60e0fe97a633a7d`，2026-11-07 查询为上游 HEAD。
扫描 `ui/` 下全部 202 个 Kotlin 文件，43 个文件包含直接动画或逐帧调度。
逐文件路径、SHA-256、动画原语及时间参数见 `droiddeck-animation-inventory.json`。
其中逐帧调度也包含焦点、布局等待，不能把所有调用都当成视觉动画。

## 动画系统

| 区域 | 上游源码 | 行为及参数 | 本次范围 |
| --- | --- | --- | --- |
| 全局运动 | FrontEndScreen、SharedMotion、Theme | `Motion.scale`、0.2/0.8/0.2/1 缓动；Rise 450ms、逐项间隔 60ms；主题颜色渐变 | 首页入场使用原生 SwiftUI；尊重减少动态效果和动画设置 |
| Steam 首页 | SteamHome、EmptyLibrary | 0 个封面时漂移标志，描边 1250ms、450ms 开始填色、900ms 弹起、1290–2050ms 翻转两圈、2200ms 落地、1250ms 涟漪；其后轻浮动，可点击重播 | 原生 Canvas 移植核心几何与时间曲线；漂移区域适配 mdeck 标题和按钮；阴影及封面涟漪着色为简化绘制 |
| 首页封面 | SteamHome | 1–3 张封面扇形浮动，9/11/13 秒往返，角度变化 2°、上浮 12pt；4 张以上为 -13° 倾斜墙，40 秒漂移；空墙 75 秒 | 使用本地已缓存封面，按数量切换；不额外下载封面 |
| 主按钮 | FrontEndWidgets | 按下缩至 0.955、悬停放大至 1.02，弹簧阻尼 0.5，阴影提升 300ms | 原生 ButtonStyle 实现按压、悬停、阴影反馈 |
| Steam 加载 | Throbber、SessionLoading | 1900ms 线性时钟驱动左半标志变形、外环旋转 360°、绿球 1→0.8→1；分段进度 1300ms；背景墙 65 秒 | 保留逐段曲线并修复 HUD 前后台驱动；在真实首帧上淡出 |
| 启动/页面扩散 | LaunchFlood、PageFlood、StepOut | 按钮扩散覆盖屏幕、背景缩至 0.96、色块收拢到绿球；页面进入退出、反向收回 | 已分析；本次采用上一轮确定的首帧淡出过渡，不声称移植 Android 的完整 Flood 系统 |
| 导航与焦点 | FrontEndRail、FrontEndContent、FocusGlide | 导航填色 220ms、按压 0.95；页面横滑/缩放/淡入，背图 700ms 交叉淡化，焦点框移动 | 保留现有 mdeck 原生导航；未在本次整体重写 |
| 设置面板 | LiftSheet、DropSheet、FrontEndSetup、SettingsWidgets | 弹簧抬升/折叠、内容逐项出现、标签滑块、开关滑动、箭头旋转、把手 2400ms 轻跳 | 已分析，保留现有功能与原生交互 |
| 库/商店/详情 | LibraryPage、FrontEndArt、CardDetailHost、GameDetail、StorePage、StoresPage、StoresMotion、StoreGameFacts、StoreAchievementsUi、AndroidAppsPage | 卡片缩放/抬升、详情展开、搜索伸展、数量/进度变化、页面切换 | 已分析，未将其 Android 动画全面改写到 mdeck |
| 下载/组件/管理 | ComponentsPage、StoragePage、StoresDownloads、UpdatesPage、GpuDriversPanel、WinComponentsEditor、SteamIntegrationGroup | 进度变化、显隐、展开折叠、集成状态闪烁/变色 | 已分析，保留原有组件后端和按钮 |
| 游戏中覆盖层 | SessionOverlay、SessionPausedOverlay、AchievementNotificationOverlay、PcKeyboard、DesktopPage | 暂停菜单、环形提示、光点、成就通知、键盘高亮、桌面卡片反馈 | 已分析，不在本次首页/Steam 加载移植范围 |
| 编辑弹窗 | AddAppDialog、ColorPickerDialog、GameEnvironmentEditor | 图标交叉淡化/缩放、清除按钮伸缩、滚动定位及焦点等待 | 已分析，保留现有编辑功能 |

## iOS 适配与验证边界

加载层位于独立的、非 key 的 UIKit HUD 窗口。其 SwiftUI `scenePhase` 可能与主 Scene 不一致，
因此不再用它决定动画时钟是否暂停，改为读取 `UIApplication.applicationState` 并观察前后台通知。
减少动态效果时显示静态构图；应用失活时暂停时间线；失败时暂停加载标志。

首帧等待必须满足实际目标进程、可见窗口和已提交的图像内容，桌面、控制台和未知窗口不能触发成功。
等待阶段与真实帧都出现后至少保留 0.7 秒，先显示下方 Steam，再进行 0.45 秒透明度动画；
动画完成回调才移除覆盖层。旧请求的完成回调不能关闭失败状态或后续请求。

iOS 申请主 JIT 池时调试器会暂停整个进程；此时任何 App 内动画都会一起暂停。
本次前端改动不能消除这个系统/调试器停顿，不改变 JIT 协议、Steam 路径或运行库。

源码与主机回归、iOS SDK 类型检查、原生 Canvas 多时刻图片对比属于组件验证；
打包成功不等于已在实体 iPad 上验收动画、Steam 登录或游戏运行。
