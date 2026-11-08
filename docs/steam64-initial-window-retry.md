# Build 27 后的 Steam 初始更新窗口退出

2026-11-08 的 `madeira-log 14.txt` 与 `madeira-log 15.txt` 给出相同终点：

- 日志 14 完成 NSIS 安装、启用已验证的 x64 引导程序，再由 explorer/services 启动 Steam。
- 日志 15 验证客户端已为 x86_64，直接启动已安装的 Steam，不再经过 NSIS。
- 两次均有 `A=42 B=42 C=42; original bytes restored=true`，入口池交接正常。
  日志 15 连续四轮探测成功。
- 两次 Steam 进程都在早期 USER32 回调/PFN 初始化前请求桌面，出现
  `[builtin-classes] deferred until this process's USER32 callbacks are ready`。
  自己的 PFN 表随后已经安装，但没有该 Steam PID 的 builtin 注册完成记录。
- Steam 输出 `failed to initialize update status ui, or create initial window`，随后以
  `0xffffff98`（-104）结束；没有进入 `steamwebhelper.exe` / `chrome_elf.dll` 加载阶段。
- explorer、services 等其他子进程仍存活，整次 Wine 会话不会结束，加载层因而一直等待 Steam 图像。

## 源码修正

`get_desktop_window()` 原先在 `thread_info->top_window` 已缓存时立即返回。
早期依赖已经取得桌面，但由于本进程尚无自己的 USER32 callback/PFN，builtin 控件注册被正确延后；
后续桌面请求全部命中缓存返回，重试机会丢失。

缓存分支现在也调用 `register_builtin_classes()`：未就绪时继续延后，自己准备好后注册一次。
注册中的 LoadImage/User32 回调可以递归查询桌面，所以增加线程局部的注册中标记，
避免同一线程重新等待 builtin mutex。完成后的热路径按 PID+PEB 在线程上缓存，不反复加锁。
父/子进程回调所有权隔离、初始 callback 清空和按进程注册规则保留。

同时，在已有进程退出通知通路中，单独识别规范 Steam Client 目录的 AMD64 `Steam.exe`
以 -104 退出。使用不含凭据的运行 UUID、一次性通知和当前会话匹配，仅在加载层仍等待
客户端首帧时显示错误。正常退出、其他状态、32 位程序、WebHelper、其他路径、
旧会话和已经显示的客户端均不使用该提示。通知在原生锁外执行，不主动终止其他子进程。

## 验证边界

`check-user-callback-ownership.py` 执行生产缓存分支、注册函数与回调代码：
保留旧缓存返回行为作为负控，检查延后初始化后重试一次、递归桌面请求不死锁、
父/子进程互不借用回调以及空 TEB/PEB 失败路径。
`check-steam-cef-guard.py` 检查真实 -104 退出资格、通知去重与锁外调用，以及生产 Swift 提示过滤。
原有 child-desktop、加载状态机、静态库链接和 iOS SDK 检查继续运行。

这些是源码、组件与编译检查。尚未构建包含此修正的新 IPA；Steam 更新窗口、Common Controls
激活上下文与后续 CEF 登录/渲染仍需新版本的真机日志验证，不能将本次组件通过当成 Steam 已修复验收。
