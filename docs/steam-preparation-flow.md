# Steam 准备流程

点击首页启动 Steam 后：

1. 检查 Wine Mono、Visual C++、Wine Gecko；复用已就绪资源，缺失项并行准备。不再下载 Madeira Dock。
2. 三项就绪后重新检查 `C:\Program Files\Steam Client\Steam.exe`，不使用点击前缓存的结果。
   宿主端识别 Steam.exe/steam.exe 的大小写，但只允许该目录中的常规文件，忽略 Dock 路径和越界符号链接。
3. 已有主程序时，使用其实际文件名启动，并补齐 `-no-cef-sandbox`、`-cef-disable-gpu`。
   新安装的默认参数仍使用完整 `SteamClient.clientArguments`，已有用户附加参数保留。
4. 没有主程序时，在唯一 Wine 会话中运行无界面的 32 位 `SteamBootstrap.exe` 控制器。
   控制器先加载 USER32 并检查窗口站、线程桌面，持有 GUI 上下文直到会话结束，不创建可见窗口。
   它启动原版 SteamSetup.exe，安装器界面始终处于 HUD 进度层下方；安装器不会关闭加载层。
   首装目标目录必须为空：游戏库 VDF 先暂存在 `Madeira/Installers/SteamLibraries.{config,steamapps}.vdf`。
   Build 20 遗留的纯配置目录完整移动到同目录下的独立 metadata 备份；含游戏或其他文件的目录停止安装并提示，不自动删除。
5. 原有窗口识别逻辑依次完成两次 Next、Install、Finish。
   从真实 NSIS 进度控件读取范围和当前位置；没有可信百分比时显示不定进度和当前步骤。
   完成页清除 Run Steam 复选框，原生进程创建钩子另行阻止安装器擅自启动 steam.exe，避免重复启动。
6. 控制器等待安装器进程句柄结束，检查退出状态，再读取固定客户端路径。
   文件不存在、安装器非零退出、启动失败等情况写入错误状态，不继续伪装成功。
   安装成功后、启动客户端前，才把两份暂存的 VDF 写入客户端；登记失败停止交接并报告错误。
7. 控制器读取目录外暂存的 `SteamDesktop.command`，按普通客户端相同的 explorer 虚拟桌面和 services 批处理路径启动该位置的 Steam。
   创建 explorer 时暂时关闭 WOW64 文件重定向，并立即恢复，确保 system32 不被重定向到 syswow64 的 32 位 explorer。
   创建失败也恢复原值；恢复失败或 explorer 非零退出写入失败状态。
   不再从非 GUI 安装控制器直接裸启动 Steam.exe。共享分辨率和客户端参数由真实 LibraryEntry 命令生成器生成；
   现有原生子进程规则继续补上兼容与客户端语言参数，更新器后续重启仍有效。客户端默认 `-language schinese`，显式语言参数保留。
   Wine server、正式 JIT 池始终保留，不重新执行第二次 Wine 初始化，不放开一次会话限制。
8. 收到控制器的 waiting 状态后，加载层才开始接受该目录 Steam/CEF 的实际可见图像。
   保留已有最短首帧等待和淡出，只有目标画面符合条件才显示界面。

控制器通过原子替换的小状态文件传递阶段，Swift 严格验证格式；每次准备先清理旧状态/取消文件。
安装进度使用带锁 C 快照，不从 UI 线程反复遍历 Windows 控件。
未知页面/意外目录稳定持续三秒后显示错误，避免页面切换的瞬间误报。
无 NSIS 子页面的安装确认/错误弹窗稳定三秒后同样报告阻塞，正文记录为 Wine Unicode 调试文本，不自动按确定。
取消加载会写取消标记，控制器终止当前子程序并拒绝继续安装到启动交接。

这里只以目标 Steam.exe 是否存在决定安装分支，遵循本次产品要求。
存在启动器不代表 Valve 的完整客户端更新已经完成，首次启动仍可能显示 Steam 自己的下载更新窗口。
没有启用任意 EXE 的跨会话连续重启；此控制器只负责这一条固定安装交接。

验证：生产 Swift 路由的真实目录检查、加载状态机、生产 C 控制器的 Win32 API 替身、
实际编译生成的 i386 GUI PE（仅导入 KERNEL32）、窗口适配器及实际 Wine 类名/Edit 读取回归、
iOS SDK 类型检查、中文本地化与缓存依赖检查。
这些是组件和编译证据，不代表已在 iPad 上验收控制器初次启动、安装到 Steam 的完整会话。
IPA 按用户要求另行构建，构建结果与真机验收分别记录。
