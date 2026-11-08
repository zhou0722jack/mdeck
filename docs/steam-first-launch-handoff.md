# 首次安装后交接与 Steam 客户端语言

Build 21 的用户日志确认安装器已以 0 退出，两个 libraryfolders.vdf 已登记，Steam.exe 已被创建并开始执行。
随后发生宿主线程 SIGSEGV，原生栈为 `req_set_win_timer+0xe0 -> call_req_handler -> thread_poll_event -> wineserver_main`，
故障地址为 `0xb8`。对照同一 IPA 的符号与源码，消息队列创建返回 NULL 后继续读取 next_timer_id 是直接崩溃点。
这不是安装器仍在运行，也不是 Steam 的普通退出码；Wine 服务端和 App 处在同一个宿主进程中，因此导致整个 App 退出。

旧日志没有记录队列创建失败的具体返回码，不能仅凭地址确定是桌面初始化、资源不足还是其他对象建立失败。
首次安装的控制器直接创建 Steam.exe，而普通“启动 Steam”经过 explorer 的虚拟桌面和 services 批处理，两者确有初始化路径差异。

## 修正

- 定时器请求检查当前队列和窗口所属线程队列。失败时保留已有状态码；缺少状态时返回 NO_MEMORY，窗口所属队列消失时返回 INVALID_HANDLE，并平衡对象引用。
- 同时给 set_queue_fd 的队列建立失败加上返回保护。没有伪造队列、清除失败状态或跳过错误接受门槛。
- 目录外暂存正常客户端的 services 批处理与 UTF-16 桌面命令。它们由生产 LibraryEntry.servicesScript 和 launchArguments 生成，携带全局/单游戏选择的分辨率与参数。
- 安装控制器检查 Steam.exe 并登记游戏库后，读取命令并创建 explorer.exe，进入普通客户端相同的桌面/服务准备路径。缺失、不可读或不完整的命令会报告失败，不退回裸启动。
- 初始控制器仍是 direct 程序，但该会话的原生桌面呈现标志为 1。继续使用原来的 Wine server 和 JIT 池，没有第二次 Wine 初始化。
- 安装器仍被加载层覆盖，加载完成仍要求目标 Steam/CEF 的真实可见图像。

## 客户端中文

账户设置中的“游戏语言”选择 depot 内容和安装记录的语言，不控制 Steam 客户端界面。
SteamClient.clientArguments 现在包含 `-language schinese`；旧的自定义参数若未明确指定语言，启动时也补上该值。
用户显式设置 `-language english` 等语言时保留该选择。语言参数位于 -applaunch 之前，并通过子进程规则传给更新器重启的 Steam。

## 验证

生产定时器请求在 ASan/UBSan 下覆盖无队列、状态保留、目标队列消失、窗口所有权、ID 分配/复用/耗尽和分配失败。
桌面命令的生产 Swift 生成器、暂存文件、分辨率、服务启动和中文参数经过主机执行及 iOS SDK 类型检查。
生产控制器覆盖登记后读取命令、成功交接、命令缺失/读取失败/截断、取消和启动失败。
这些是源码/组件验证。Build 22 已打包；以下为该包后续收到的真机失败及修正，尚未重新打包验收。

## Build 22：安装完成后创建桌面失败

用户日志 `madeira-log 5.txt`（2026-11-08 07:15，Build 22）记录：

- 入口 JIT 探测返回 42，正式 JIT 池已建立；三个组件已就绪，字体注册 `registered64=1 registered32=1`。
- NSIS 完成并以 0 退出，控制器登记两个 VDF 后调用 `C:\windows\system32\explorer.exe`。
- 实际装载的是 `C:\windows\syswow64\explorer.exe`，PE Machine=0x14c。i386 控制器的 WOW64 文件重定向仍在生效。
- explorer 的 `CreateDesktopW("shell", ...)` 失败，错误码 6（无效句柄），随后 explorer 和控制器以 1 退出。没有进入 Steam/CEF 的启动阶段。

控制器此前仅依赖 KERNEL32，本身不初始化 USER32；第一次加载 USER32 的是短命的安装器。
`build/win32u-unix/class_ios.c` 的 `init_user` 由宿主 `pthread_once` 控制，包含 `winstation_init`。
后来子进程的补偿逻辑位于 `get_desktop_window` 失败路径，而 explorer 在此之前就调用 `CreateDesktopW`。
日志没有直接列出窗口站句柄，但此初始化差异可解释无效句柄；路径重定向由实际映像装载路径直接确认。

修正只涉及安装控制器：

1. 在启动 NSIS 前动态加载 USER32，检查控制器的窗口站和线程桌面，并将模块保留到进程退出。
   让长命控制器持有 GUI 上下文，不依靠安装器退出后重建；不创建可见窗口。缺少模块、接口或有效句柄直接报告失败。
2. 仅在创建 system32 explorer 的调用范围内使用 `Wow64DisableWow64FsRedirection`，随即恢复原值。
   创建失败也恢复；恢复失败终止刚创建的 explorer 并关闭句柄，不继续报告等待成功。
   控制器运行于原来的 aarch64/WOW64 会话，正式 explorer 使用普通 Steam 启动路径的原生版本。
3. explorer 非零退出也写入 `stage=failed`，避免旧的 waiting 状态继续保留。

控制器测试覆盖 USER32/接口/窗口站/桌面缺失、关闭/恢复重定向失败、创建失败时恢复及错误码保留、
explorer 非零退出；成功路径要求 GUI 上下文先于安装器建立，安装器退出后才暂时关闭重定向并启动桌面。
生成的 PE 仍只静态导入 KERNEL32，通过 LoadLibraryW 使用包内 USER32。主机替身测试不代表真机交接已通过。
