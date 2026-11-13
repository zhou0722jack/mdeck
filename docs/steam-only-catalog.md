# Steam 专属游戏库与原生下载商店

## 上游核对

- DroidDeck 固定提交：`aba55031c331cd0991c3d36788fb903a3ca30e78`。
- 参考文件：[LibraryPage.kt](https://github.com/Droid-Deck/DroidDeck/blob/aba55031c331cd0991c3d36788fb903a3ca30e78/app/src/main/java/com/droiddeck/launcher/ui/LibraryPage.kt)，SHA-256 `d0e250924d933aad9d589e3d07b3feb61a5e2aad28655a623a674538b8db1521`。包括 `LibraryDisplay`、`installedFirst`、`LibraryTile`、`ArtCard`、`LibraryHeader`、过滤/排序/显示菜单和 `CardDetailHost`。
- [madeira-dock README](https://github.com/willfaust/madeira-dock/blob/67780ba92e60dbfac4fe80eaf2ce34b9ea1a1c60/README.md) 固定提交 `67780ba92e60dbfac4fe80eaf2ce34b9ea1a1c60`：Dock 是 Valve 客户端的无界面宿主，负责真实登录、授权与启动已安装游戏；README 明确说明它不负责游戏下载。

因此沿用 SwiftSteam 原生登录、许可证读取、depot 下载和安装记录写入功能。没有恢复 Dock 组件自动下载，也没有修改 madeira-dock 或 FEX 子模块。DroidDeck GPL 许可和既有归属声明保留；这里是 SwiftUI 原生移植。

## 界面

主导航的游戏库和商店都使用 `DeckSteamCatalog`，只包含 Steam 游戏。其他平台不出现在这些页面和账户设置列表中。已有安装文件与元数据不删除，手动 EXE 继续从“应用”进入。

游戏库移植 DroidDeck 的宽版 16:9 卡片、5:7 竖版封面、列表、五档尺寸（0.75/0.875/1/1.2/1.45）、名称/大小开关、安装状态过滤、最近游玩/名称/大小排序、已在设备上的游戏优先排列。卡片使用 10pt 圆角、底部标题渐变、角标、细进度条和 0.985 按压弹簧缩放。打开游戏时，在同一页面中通过封面几何过渡显示详情；减少动态效果设置关闭动画。手柄支持卡片导航、确认与返回。

游戏库和商店共用显示偏好，设置中的旧捏合网格开关替换为对应的新显示选项。旧网格的数据类型和源文件仍保留，以免破坏已有数据与其他模块。

账户游戏合并、过滤和排序只在所有权列表、本地安装、下载任务成员、过滤条件或排序依据变化时更新。下载进度更新只刷新可见卡片，不对整个账户库重复排序；卡片大小查询使用预计算字典。

## 登录后不启动客户端即可下载

Windows Steam → App 商店的自动授权同步见
[登录同步流程](steam-client-signin-sync.md)。同步经 Valve 验证后存入同一个 Keychain
登录项，商店沿用下列原生下载流程；Windows 会话期间保持连接隔离。

1. 在商店或 Steam 设置内登录 Steam，凭据继续保存在系统 Keychain。
2. 原生连接从 Valve 获取账户许可证与可安装的 Windows 游戏；商店展示账户已拥有的游戏。
3. 点击“下载”进入已有 `SteamOwnedLibrary` 队列，不申请正式 JIT 池、不启动 Wine、SteamSetup、Steam.exe 或 Dock。
4. 支持暂停、继续与失败重试。下载选项继续提供安装位置、语言、分支与 DLC 选择。
5. 内容由 Steam 内容服务器提供，沿用真实授权、分块校验和续传；安装完成后由 `AppManifestWriter` 写入标准 appmanifest 和 InstalledDepots。
6. 已有 Steam.exe 时，将完成的游戏库路径合并登记到交互客户端的两个 `libraryfolders.vdf`，保留已有条目和元数据。客户端尚未安装时不写安装目录，首装时先在目录外暂存，安装器退出后、启动 Steam 前才写入。客户端运行时也不写这些文件，下次启动前再登记。登记失败保留已下载的游戏并报告错误。
7. 游戏库重新扫描安装记录，显示“开始游戏”。点击后沿用全局 Steam 设置与客户端 `-applaunch` 路线。用户也可以启动大屏 Steam，从其游戏库运行相同安装。

历史原生下载目录 `Program Files (x86)/Steam/steamapps` 继续有效，它只是游戏库文件目录，不会因此下载 Dock 客户端。交互客户端自己的 `Program Files/Steam Client/steamapps` 也允许由原生下载器更新。外置游戏库保留原有权限与路径检查。

## 删除本地游戏

游戏库和商店的已安装游戏详情提供“删除游戏”；长按游戏卡片也可进入相同确认流程。支持历史原生下载目录、64 位客户端游戏库、`Program Files/Steam Client32/steamapps` 和已登记的外置游戏库。删除不需要登录 Steam。Windows 会话或启动准备期间不能删除，文件搬移和该游戏的云存档操作也会阻止删除。

确认提示明确说明删除范围：游戏安装目录（包含其中的模组和存档）、该游戏的下载暂存文件、安装记录和本地游戏设置。目录外的存档与账号游戏所有权保留。正在下载或更新的游戏先停止写入，再删除；删除期间显示进度，操作真正成功后才退出详情并提示成功，之后可重新下载。失败保留错误提示，不提前移除本地库条目。旧设置页的卸载入口同样等待成功后再关闭。

删除路径继续执行目录穿越和符号链接检查，安装记录与所选目录不一致时拒绝删除。其他 Steam 应用使用相同安装目录时拒绝删除并提示从 Windows Steam 卸载；共享 depot 的独立安装保留自己的文件和记录。

商店提供官方购买页面入口；购买或添加到 Steam 账户后的游戏通过刷新库获取。此页面的直接下载范围是账户拥有的 Windows 游戏。

## 验证边界

主机执行测试验证游戏合并、过滤、稳定排序和卡片尺寸；新原生页面及全部布局、下载操作、详情过渡与手柄入口经过 iOS SDK 类型检查。实际生产安装记录写入器、游戏扫描器和客户端 VDF 登记函数组合测试验证两个客户端目录能够识别相同安装。既有下载器测试使用合成账户、清单和本地服务器校验，不使用用户凭据。

尚需真机验收：真实账户完整下载、iOS 后台下载、Steam 首次更新后保留游戏库登记、从游戏库和大屏 Steam 启动实际游戏，以及 iPad 上的布局与过渡观感。界面实现阶段只验证源码，IPA 按用户要求另行构建；构建成功也不等同于上述真机验收。
