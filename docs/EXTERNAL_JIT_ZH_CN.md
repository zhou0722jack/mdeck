# 从 StikDebug 脚本启动 Madeira

在“设置 → JIT”中选择“外部 StikDebug 脚本”。全新安装默认选择此模式；
升级会保留以前选择的 JIT 方式，需要手动切换一次。

## 设置一次

1. 在 Madeira 的 JIT 页面点击“导出 Madeira JIT 脚本”，保存
   madeira-jit.js。它与项目自带脚本是同一份文件。
2. 在 StikDebug 的 Scripts（脚本）页面导入这个文件。
3. 在 StikDebug 中为当前安装的 Madeira 指定 madeira-jit.js，
   使用应用自己的脚本分配，而不是只执行一次普通附加。
4. 在 StikDebug 中配置这台设备的配对文件，并连接 LocalDevVPN。
   Madeira 在外部模式下不会代为处理这些设置。

## 每次启动

1. 从 StikDebug 使用指定的脚本启动 Madeira。
2. 回到 Madeira，选择游戏并开始。
3. 开始游戏前保持脚本运行。Madeira 会通过脚本准备 JIT 内存；
   完成后自动解除附加，并继续启动 Wine 和游戏。

建议先运行脚本，再选择游戏。如果 StikDebug 重新启动了 Madeira，
旧进程中等待启动的游戏不会保留，需要重新选择。

“检查外部脚本附加状态”只检查并等待外部调试器，最长 90 秒。
它不会打开 StikDebug、强制发送脚本或改用内置 JIT 助手。
可以点击“停止等待”；停止后不会自动启动先前等待的游戏。

该方式仍需要允许调试的签名、有效配对和可用的调试连接。
仅有 JIT 标志、调试器却已离开时，不会被判定为就绪。

## 旧方式

“自动”“StikDebug”和“内置 StikJIT”仍保留在方式选择器中。
选择它们时，继续使用原来的应用内启用流程。
