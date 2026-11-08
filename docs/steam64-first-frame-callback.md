# Build 26：64 位 Steam 在首帧前进入继承的 WoW64 回调

用户日志 `madeira-log 12.txt`（2026-11-08）记录首装控制器已完成安装、启用 64 位种子程序，
随后加载层停在“等待 Steam 首帧”。

## 日志证据

- 第 5130 行：`verified x86_64 bootstrap activated after setup`。
- 第 5219 行：原生 system32 explorer 已创建，并恢复了安装控制器的 WOW64 文件重定向。
- 第 5736 行：安装控制器交接完成，开始等待 Steam 图像。
- 第 6928、6964、6968 行：Steam 子程序为 `Machine=0x8664`，使用独立 ARM64EC ntdll，
  不是继续执行安装器放下的 32 位 `Steam.exe`。
- 第 8128 行：窗口回调 id=15；调用链为 `dinput8` 的进程附加注册类，进入
  `NtUserRegisterClassExWOW -> get_desktop_window -> register_builtin_classes -> LoadImageW -> KeUserModeCallback`。
- 第 8177、8187、8188 行：实际进入 `wow64win`、`wow64.dll` 和
  `libwow64fex.dll+0x100d38`；第 8338–8343 行为 `c0000005`，读取空地址。
- 第 8648–8650 行：反复异常后故障线程被终止。没有 CEF 加载和真实 Steam 首帧记录。

控制器的 waiting 状态证明它已启动桌面交接，不证明 Steam 已完成依赖初始化或绘制。
这次故障发生于窗口初始化，不能用关闭首帧判断或延时移除加载层修复。

## 对应源码与修正

`wine_ios_child_main` 从初始进程复制整个 PEB，却保留 `KernelCallbackTable`。
初始进程是 32 位安装控制器时，表项属于其 WoW64 桥；64 位 Steam 的 TLS/CPU 状态不提供
WoW64 回调所需的 32 位上下文。当前子程序 USER32 尚未进行自己的进程附加，
`NtUserInitializeClientPfnArrays` 还没有为它发布客户函数表，而 DirectInput 的初始化
已经触发 Unix 侧的内置控件注册。`LoadImageW` 因而调入继承的兼容表项。

修正：

1. 创建子进程 PEB 时清空 `KernelCallbackTable`，由该进程 USER32 或 WoW64 初始化自己的表。
   不修改父进程或兄弟进程的表。
2. 内置控件注册要求本进程的回调表和 PFN 表都已就绪；依赖 DLL 提前注册类时先推迟，
   不写入“注册完成”记录。USER32 就绪后的下一次 GUI 请求正常注册。
   内置类的 USER32 模块句柄也按当前 PEB 解析。
3. `KeUserModeCallback` 在 TEB、PEB 或回调表缺失时，先清空输出并返回
   `STATUS_DLL_INIT_FAILED`，不访问 syscall frame 或跳入未知回调。
4. 原 `[kcb] SESSION THREAD, CHILD DISPATCHER (BUG)` 标记使用会漂移的全局 `peb` 判断，
   会误标正确选中的私有 ARM64EC dispatcher。改为如实记录 process-specific dispatcher；
   该标签本身不作为根因。故障依据是实际 WoW64 调用栈和其未建立的上下文。

Steam 仍使用官方 64 位程序，首帧条件、动画时长、JIT 池及 FEX 子模块均不修改。

## 验证边界

`check-user-callback-ownership.py` 执行生产 PEB 清理、内置控件注册和
`KeUserModeCallback`，在 ASan/UBSan 下使用 Build 26 注册顺序作为负对照：
旧顺序在初始化前到达父进程兼容回调，新顺序推迟并在本进程初始化后只注册一次。
覆盖缺失 TEB/PEB/回调表、独立兄弟进程、父进程保留，以及回调返回数据。
这不是实际执行 FEX 或真实 Steam。

子桌面回归、缓存依赖和既有启动/首帧状态机另外检查。
仍需新 IPA 真机验证：首装后 Win64 Steam 完成 USER32 初始化、开始更新配套组件、
产生目标窗口图像，并由加载层正常淡出。构建或主机组件通过不代表该真机链路已验收。
