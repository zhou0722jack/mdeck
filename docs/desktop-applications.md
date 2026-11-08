# Wine 桌面中的已安装应用

“打开桌面”仍然启动同一 Wine 容器的 Explorer 桌面。进入时，加载画面等待
`/desktop=shell` 的 Explorer 完成桌面初始化，并提交一帧可见的桌面图像。
合成器的青色底色、其他窗口的 GDI 帧、初始化前排队的帧都不能提前结束加载。
超过 30 秒仍可使用原有的“显示游戏画面”按钮手动查看。

## 快捷方式来源

启动 Wine 前，`DesktopApplications.swift` 向 `C:\users\Public\Desktop` 同步以下应用：

- 当前用户和公共“开始菜单\程序”中的应用快捷方式，保留原始启动参数和工作目录。
- Wine 的 App Paths、卸载登记中的可运行主程序。卸载器、修复工具、系统组件和
  `C:\windows` 中的内置工具不会因此添加到桌面。
- `C:\Program Files\Steam Client\Steam.exe`。
- Steam 客户端和 mdeck 下载目录，以及 `libraryfolders.vdf` 引用的 C 盘游戏库内，
  清单标记为已安装且安装目录仍存在的游戏。游戏通过 `Steam.exe -applaunch <id>` 启动。
- 已添加到 mdeck 游戏库的非 Steam 便携应用。

Wine 会读取用户桌面和公共桌面。已有的桌面快捷方式优先，按“目标程序 + 参数”
去重。同名但不同的程序使用带序号的文件名。缺少可提取图标时，Explorer 显示
通用应用图标；生成的快捷方式和 Wine 的读取路径支持 Unicode 中文目录。

运行期间在前台约每 15 秒重新检查一次。Explorer 的目录通知会刷新新增或变更的
快捷方式，无需关闭桌面。进入后台或 Wine 已停止时跳过检查。

## 文件维护与启动参数

`.mdeck-applications.json` 只记录 mdeck 自动生成或复制的快捷方式及其内容哈希。
同步仅更新、清理仍与记录一致的文件。安装程序原有的快捷方式及用户改动的文件
不会被覆盖或删除。源登记、清单或游戏库读取不完整时，本次保留旧的自动快捷方式。

桌面会话沿用 Steam 全局兼容参数和语言选择，保持桌面自身的分辨率及运行配置。
子进程参数规则仅匹配 `steam.exe`。此会话设置 `MADEIRA_CHILD_ARGS_FIRST=1`，将
Steam 参数放在快捷方式的 `-applaunch` 之前，保留后面游戏自己的参数。
正常 Steam 启动及其他程序沿用原先的参数追加行为；会话结束清除该顺序开关。

只有安装目录、没有快捷方式或明确启动登记且包含多个程序的应用，无法可靠判断
主程序。此时保留现有文件，用户可通过“添加可执行文件”选定入口，随后自动同步。
扫描器不会运行任何 EXE，也不会改写安装登记或 Steam 清单。

## 验证

`tests/host/check-desktop-applications.py` 使用临时 Wine 目录执行生产 Swift 发现逻辑，
独立验证 Shell Link 字节布局，并用补丁中的 Wine 读取函数确认中文目标路径。
同时运行 Explorer 图标/目录监听和桌面就绪状态检查，覆盖旧监听器的失败对照、
提前排队的空白帧、其他窗口、旧会话、隐藏窗口以及参数顺序。

日志可搜索 `[desktop-apps]`、`[desktop-ready]` 和
`[launch-view] dismissed reason=desktop-ready-frame`。
这些主机检查和 iOS SDK 类型检查不代表 iPad 真机验收；此修改未构建 IPA。
