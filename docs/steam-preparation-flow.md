# Steam 准备流程

点击首页启动 Steam 后：

1. 检查 Wine Mono、Visual C++、Wine Gecko；复用已就绪资源，缺失项并行准备。不再下载 Madeira Dock。
2. 三项就绪后准备 Valve 官方 Win64 引导程序，整个过程仍在动画的组件下载阶段，不先启动 Wine 或分配正式 JIT 池。
   下载 `steam_client_win64` 清单对应的已固定版本 `steam_win64.zip`，验证包大小、SHA-256、解压后映像 SHA-256，以及 `0x8664`／PE32+ 文件头。
   已验证的引导程序缓存为 `Madeira/Installers/Steam64.exe`，重试可复用；已有合法 64 位 Steam.exe 时直接复用，不降级到固定种子版本。
   下载结束后重新检查是否有运行中的 Wine 会话，再重新检查固定客户端目录，不使用点击前缓存的结果。
3. 已有主程序为 32 位时，将原文件备份为 `Madeira/Installers/Steam-before-win64-{UUID}.exe`，原子替换这一文件为官方 64 位引导程序。
   `config`、`userdata`、`steamapps`、`package` 及游戏内容不删除。64 位引导程序后续按自己的 Win64 更新路线准备配套客户端和 CEF。
   宿主端识别 Steam.exe/steam.exe 的大小写，但只允许该目录中的常规文件，忽略 Dock 路径和越界符号链接。
   使用实际文件名和文件架构启动，并补齐 `-no-cef-sandbox`、`-cef-disable-gpu`；移除旧 `-cef-force-32bit` 参数。
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
   首装控制器备份安装器放下的原始主程序到 `Madeira/Installers/Steam-before-win64-installed.exe`，
   检查缓存映像为 64 位，复制到临时文件后再次检查，再原子启用为 `Steam.exe`。
   任意校验、备份、复制或替换失败都停止，不回退为启动 32 位客户端。NSIS 和控制器本身仍可为 32 位，最终启动的是已验证的 64 位客户端。
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

目标 Steam.exe 是否存在决定是否需要 NSIS 建立初始安装；其实际架构决定是否需要迁移到 64 位。
存在 64 位引导程序不代表 Valve 的完整 Win64 客户端更新已经完成，首次启动仍可能显示 Steam 自己的下载更新窗口。
没有启用任意 EXE 的跨会话连续重启；此控制器只负责这一条固定安装交接。

验证：生产 Swift 路由的真实目录检查、加载状态机、生产 C 控制器的 Win32 API 替身、
实际编译生成的 i386 GUI PE（仅导入 KERNEL32）、窗口适配器及实际 Wine 类名/Edit 读取回归、
iOS SDK 类型检查、中文本地化与缓存依赖检查。
这些是组件和编译证据，不代表已在 iPad 上验收控制器初次启动、安装到 Steam 的完整会话。
IPA 按用户要求另行构建，构建结果与真机验收分别记录。

## Win64 分发依据与验证

官方清单：[steam_client_win64](https://client-update.akamai.steamstatic.com/steam_client_win64)。
2026-11-08 核对版本 `1792618285`，种子包 `steam_win64.zip.9ddc7f402ba9bec08b7dbee2cf6ee37d21e1b4e0`，
包大小 2,692,595 字节，包 SHA-256 `9a5aba7f8b5341344717f4a07027ac128e6913bb918454672e843fb5f7e61468`。
其中唯一文件 `steam.exe` 为 5,823,128 字节、AMD64/PE32+，
映像 SHA-256 `f8a4ca44008c516eebecafaa4bc26772b2a6eb0fef8034bce56a3311e21ab705`。
后续完整客户端资源由该官方引导程序更新；这里没有从 Dock 的固定组件集合拼接 Steam UI。

`check-steam-client64.py` 执行生产 ZIP 解码和迁移代码，覆盖哈希/架构拒绝、原程序备份、
配置与游戏保留、已是 64 位时不覆盖、路径与取消检查；可用 `--official-archive` 验证真实种子包。
安装控制器覆盖 64 位源/副本检查、备份、复制和启用失败；加载状态机覆盖下载失败重试和取消后的旧任务不得启动。
这些组件检查和官方包静态检查不等于 iPad 上 Win64 Steam/CEF 更新、登录和渲染已验收，仍需新 IPA 真机验证。
