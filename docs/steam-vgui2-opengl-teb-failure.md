# Steam vgui2_s.dll 初始化失败：OpenGL WoW64 TEB 转换

输入证据：`SteamSetup.exe-2026-11-07_15-31-18.txt`、`IMG_2847.HEIC`。
日志设备运行的是 0.2.0 / Build 14，截图提示：
`Fatal Error: Could not load module 'bin/vgui2_s.dll'`。

关键顺序：

1. 安装程序进入 Steam 更新、展开文件、重启 `steam.exe` 的路径。
2. `vgui2_s.dll` 已读入，分配 TLS 槽；随后读入其依赖的 COMDLG32、MSIMG32、OPENGL32。
3. 原生调用表显示 `opengl32 (winios WGL) -> wow64 table`。
4. `wow64_thread_attach+0x4` 访问 `0x302fdc` 时发生 SEGV。
   此时原始参数 `x0=0x7300302000`，寄存器 `x8=0x302000`，故障偏移为 `0xfdc`。
5. 重试仍访问同一地址；卸载模块后才报告 `vgui2_s.dll status=c0000135`。

Wine 的 `TEB32.WowTebOffset` 正好位于 `0xfdc`。
`wow64_thread_attach` 把完整外层参数送到 `get_teb64((ULONG_PTR)args)`，
但 `get_teb64` 接收 `ULONG`，将完整地址截成 `0x302000`，再用 `ULongToPtr` 直接解引用。
iOS 不在这个低地址放置 TEB32，所以这与日志的故障指令和地址一致。

修正通过 `build/windows-runtime/patches/0002-opengl-wow64-teb-host-pointer.patch` 携带：
`get_teb64` 改用 `ULONG_PTR` 接收参数。iOS 的完整 host 指针直接使用；
结构内嵌的 guest PTR32 则通过现有 `ios_wow_host_ptr` 加入当前进程窗口。
随后按有符号 `WowTebOffset` 寻找 TEB64；非 iOS 保持原先的 `ULongToPtr` 分支。
不修改 Wine 子模块指针，也不修改 FEX、Steam 文件或全局访存恢复逻辑。

回归检查直接提取补丁后的生产函数，实际分配高地址内存，覆盖完整 host 指针、
guest PTR32、正负偏移和 `wow64_thread_attach` 写入；旧函数作为负对照在子进程中故障。
补丁可应用性与回归已接入云端预检查。
主机指针回归通过不代表真实 Steam 已进入主界面；需要新包及 iPad 日志验收。

无需仅凭这个弹窗下载第三方 DLL 或删除现有 Steam 安装。
