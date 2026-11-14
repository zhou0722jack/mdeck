# CEF 热点检测

入口：Steam 设置 → 高级 → 诊断 → **CEF 热点检测**。默认关闭，配置键
`env.MADEIRA_STEAM_HOTSPOT = 1`，下次启动 Steam 时生效。游戏配置覆盖全局配置；
缺失或 `0` 为关闭。与 CPU 性能日志、窗口检测、分配与重试检测分别控制。

开启后从 Wine 会话开始等待 15 秒，再采样最多 30 秒。每轮相隔至少约 200 ms，
最多选择一条 CEF 名称匹配的忙线程和一条未命名原生忙线程。只选择上一轮以来累计
CPU 时间增加至少 2 ms 的线程；第一轮只建立基线，不采样。主线程、自身、已经暂停
的线程、实时调度线程和其他命名线程不选中。CEF 名称匹配不是程序归属认证，日志使用
`cef-name`；无 TEB 的未命名线程使用 `unnamed-no-teb`，不据此断言它一定是原生线程。

每次通过 Mach 短暂暂停一条线程，读取寄存器及最多四次受保护的小块内存：
32 字节 frame 前缀、4 字节 block header、32 字节 block tail 和重读的 4 字节
header。只接受包含当前宿主 PC、大小及地址通过边界检查的代码块。随后先恢复线程，
再查模块、分类、聚合、输出日志。采样期间不持有控制锁，
不查 Wine 模块、不做符号解析、不分配内存或打印日志。不能将本功能称为无干扰采样。

限制为最多 300 次暂停尝试、单次暂停操作保守计时预算 5 ms、累计预算 50 ms。
预算用于测到超限后停止后续采样，并非每次暂停都能满足硬实时上限。线程状态读取
失败仍恢复；恢复错误最多重试三次，仍失败时记 `resume_failed` 并停止采样，不能把
这种情况当作正常完成。记录失败、未解析和表容量溢出，绝不把失败当作没有开销。

达到时间/样本/暂停预算后自动停止；切出 App、App 失去活动状态、会话结束、参数
被拒绝或点击 **停止 CEF 热点检测** 也停止。手动停止不清除配置，下一次 Steam
启动仍按开关决定是否重新采集。后台返回不自动重启采样。

## 日志

开启后同时保留轻量“性能日志”和窗口检测，运行同一页面的静止、滚动和切页操作，
约 45 秒后导出同一次日志，搜索：

```text
[steam-hotspot]
[steam-hotspot-thread]
[steam-hotspot-pc]
```

每约 5 秒汇总，自动完成时输出最终汇总。计数在同一 session 内是累计值，不能将
每次汇总相加。session 在取消/重启后变化，旧采样不并入新会话。

- 总行：尝试、成功抓取、暂停/状态读取/恢复失败、暂停耗时、模块元数据能力及表
  溢出。`reason` 为 waiting、sampling、duration-complete、sample-budget、
  single-hold-budget、total-hold-budget、resume-failed 或 main-thread-unavailable。
- 线程行：Mach thread ID、可读时的 Windows PID/TID、线程名、选取分组、样本
  分类、选中轮次对应的 CPU 增量和直方图替换次数。`selected_cpu_ms` 不是整条线程
  的完整 CPU 时间，完整轻量计数仍看 `[xp-t]`。
- PC 行：宿主 PC、模块名和相对地址（可用于同版本离线解析），有符号时附函数名。
  不输出完整文件路径、窗口标题、账户或图像内容。

执行位置分类覆盖 A/B 内的翻译代码、C 区翻译代码、能识别的 PE 镜像（含 A/B
镜像副本）、宿主库及 unknown。宿主 PC 分类不依赖能否读出 guest RIP。原生线程
没有 Windows TEB 也可采样；TEB 获取失败时显示 PID/TID 为 0、`teb_lookup` 能力
状态和无法解析的信息，不猜测归属。

JIT 采样优先输出 `guest_block=模块+偏移`，这是包含当前宿主 PC 的翻译块的
入口 guest RIP 对应模块，偏移按 256 字节归组，不是精确当前 x86 指令。
无法取得合法 block tail 时仍输出 `guest_hint`，仅是 frame 候选值，不按它计算
精确 guest 函数占比。模块表按线程所在进程读取，32 位先验证 WoW64 CPU area、
TEB32 自指针，再遍历 PEB32 的 guest loader list；64 位使用原生 loader list。
未解析模块仍明示 `unresolved`，不猜测 libcef.dll。宿主分类不依赖 guest 解析成功。
`TH_STATE_RUNNING` 包括可调度状态，采样选择也有偏向；样本分布不是精确 CPU
百分比，不用于认定 GPU 饱和。

固定最多保留 32 条选中线程记录和每线程 24 个位置候选。每次输出样本最多的 8 条
线程及每线程 2 个位置候选。位置使用有界 Space-Saving 计数，以免后期热点被早期
冷位置挡住：真实计数在 `samples_min` 与 `estimated_samples` 之间，误差上界为
`error_bound`。原生位置按 256 B、JIT 页按 4 KiB 归组，原始 PC 也保留。替换或线程
表满会明示，不能将输出解释成所有线程的完整分布。

## 验证边界

GitHub Actions 执行生产预算/暂停恢复/分类代码和带可控 Mach 后端的生产采样器，
并做完整源文件的 iPhoneOS 语法检查及归档链接验证。控制后端不会暂停真实 Wine
线程；设备上的耗时、热点数据及暂停对交互的影响需要安装后复测。

## FEX 分段计时

同一开关额外启用 `[steam-fex]` 和 `[steam-fex-stage]`，约每秒输出一次，
正常结束输出最终累计快照。宿主在最初 15 秒内也发现忙 CEF 线程并将其 TEB 登记
到固定共享表，计时从登记后开始，整个会话最多约 45 秒；暂停采样仍只在后 30 秒。
计时不覆盖登记前的冷启动、未选中的线程或发射汇编的 L1 快速查找。

| stage | 边界 | stride |
| --- | --- | --- |
| compile-block-inclusive | C++ CompileBlock 完整调用，含原有诊断及下列子阶段 | 64 |
| lookup-cpp | FindBlock，含其内部获取锁和查找 | 64 |
| compile-code-inclusive | CompileCode 的 IR 生成、重查、发射等；失败/竞态提前返回也计入 | 1 |
| cache-clear-inclusive | LookupCache::ClearCache / Arm64JITCore::ClearCache | 1 |
| map-migrate | ChangeGuestToHostMapping，含线程本地缓存清理 | 1 |
| sweep-inclusive | IosMaybeSweepCodeBuffers，含无须迁移的提前返回 | 1 |

`calls` 是登记线程进入阶段、成功获得统计 try-lock 后的累计次数；
`timed` 是完成且成功记录的计时样本数。stride=64 只计时第 1、65……次调用，
`sampled_wall_ms` 是这些样本的耗时总和，**不是全量查找耗时**。
`mean_ms`、`max_ms` 只覆盖已计时样本；全部采用 ARM 虚拟计数器及其频率计算
经过时间，包含调度、锁等待和子调用，不是线程 CPU 时间。阶段相互包含，
不能相加，也不能从线程 CPU 时间减去它们来估算执行 guest 代码的时间。

统计端不分配、不写日志、不等待锁，发生竞争或嵌套抢占就丢弃该次统计并记录
`dropped`。宿主输出 `report_busy`、`enroll_failed`；表固定 64 槽，每次登记/查找
最多探测四槽。没有空槽则拒绝登记，不驱逐同一会话已登记线程。TEB 回收后 Mach
线程 ID 不同也不复用同一会话槽，防止混合两个线程。
`attached_paths` 的位 1 表示 WoW64 接口已连接，位 2 表示 ARM64EC 已连接；
0 必须解释为尚未连接/旧运行库，不能据零计数宣称没有编译开销。

共享区由宿主永久保留，PE 仅通过 App 启动时发布的内部地址读取这个版本化 ABI，
没有跨 PE/原生的函数指针调用。停止/失活会立即清除活动 epoch；跨停止、跨会话的
未完成 scope 不会写入下一会话。每行均为本会话累计值，不叠加不同秒的快照。
手动取消期间来不及输出的尾部依最后一份快照为准；报告线程与生产线程并发，
不能把某一行当作所有阶段的同一时刻原子快照。
