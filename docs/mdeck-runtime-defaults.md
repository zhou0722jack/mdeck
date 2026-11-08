# mdeck 默认内存设置与 Steam 运行配置

首次打开本次更新时，全局“内存与同步”默认值为：

| 选项 | 默认值 |
| --- | --- |
| JIT 内存池 | 1152 MB（申请目标，实际分配以日志为准） |
| 显存 | 自动 |
| 交换层 | 4 GB |
| 交换覆盖范围 | 大块分配，默认 8 MB 以上 |
| 共享内存池 | 6 GB（目标容量） |
| 32 位程序 | 仅共享 RAM |
| 同步引擎 | Fastsync |
| 节能模式 | 关闭 |

`MadeiraConfig.installMdeckRuntimeDefaults` 在界面与运行库启动前更新
`Documents/madeira.cfg`。它只替换上述选项，以及会影响覆盖范围的旧门槛参数，
保留其他设置与注释。旧文件备份为
`madeira.cfg.before-mdeck-defaults-v1.bak`。文件中的版本注释记录这次更新已经完成，
用户之后在设置里选择其他值不会在每次打开时被重置。

“Steam 设置 → 高级 → Steam 运行配置”使用
`C:\Program Files\Steam Client\Steam.exe` 对应的 `GameProfile` 文件。
推荐模板版本为 7，完整采用用户提供的 20 项参数：头部预留为 48 MB，移除
模板中的 `swap-mb`、`swap-min-mb`、`env.MADEIRA_SWAP_COVERAGE` 和
`donor-pool-mb`，从而继承全局内存选项。

`GameRecommendations.installSteamRuntimeDefaults` 在本次更新首次打开时将这一
独立文件替换为新模板；旧文件备份为原文件名加
`.before-mdeck-steam-runtime-v1.bak`。它不修改 Steam 的分辨率、画面、控制等字段。
完成标记只在写入并核对成功后保存，失败可以重试。之后编辑运行配置会保留，
“恢复推荐设置”则写回同一份新模板。

旧游戏库中 Steam 全局条目的内联 `config` 不再覆盖上述独立文件。
使用独立设置的 Steam 游戏仍保留自己的配置。

相关验证：`check-runtime-settings.py`、`check-game-recommendations.py` 和
`check-steam-client-routing.py`。验证覆盖全新配置、旧配置更新、备份、失败重试、
后续编辑保留，以及 Steam 独立游戏设置的保留。主机执行和 iOS 类型检查不代表
真机内存分配或性能结果。
