# 编译原因日志

入口：**Steam 设置 → 高级 → 诊断 → 编译原因日志**。默认关闭，下次启动 Steam
生效。与 CEF 热点检测、CPU、窗口和分配诊断独立；不需要开启热点检测。
运行期间可点 **停止编译原因日志**。手动配置：

```ini
env.MADEIRA_STEAM_COMPILE_REASONS = 1
```

从 Wine 启动起最多 45 秒、每秒汇总，最多记录 400,000 次已完成的编译尝试。
失去前台活动状态、会话结束或手动停止时取消。重新回前台不自动重启；下次启动
Steam 根据保存的开关重新启用。本功能不暂停任何线程。

## 分类与含义

| 字段 | 记录的事实 |
| --- | --- |
| first_observed | 本次观察窗口中，该 PE 实例、代码管理器、guest RIP 和编译模式首次保留了有效指纹记录 |
| changed_content | 与该键的上一条记录相比，解码形状相同，实际解码字节指纹改变 |
| same_content_new_generation | 解码形状和字节指纹相同，输出到了另一代代码缓冲区 |
| same_content_same_generation | 内容指纹相同，输出代也相同，仍再次生成代码 |
| unknown | 解码形状变化、指纹超限/不可用、代信息缺失、历史表探测溢出、实例配额不足或并发完成顺序不可靠 |

**这些是编译来源的观察分类，不是因果证明。** 首次观察不等于整个进程生命周期
第一次编译，开始记录前可能已有编译；同内容新代不能单独证明“换代是唯一原因”；
内容变化也不能单独证明是 SMC 写入，还可能是代码映射变化。不会据此复用代码或
改变失效策略。

每个真正进入后端并生成有效入口的调用恰好进入一个分类。五类之和的分母是
`generated`，不是 `completed`。其他结果单独计数：`raced` 为 IR 已生成后复查发现
别人编译完成；`failed` 包括未得到 IR 或后端没有有效入口；`delivery` 为异常投递
期间的特殊编译。`generated + raced + failed + delivery = completed`。

## 经过时间分解

原有每类 `total_wall_ms` 保留，统计 generated 调用从 CompileCode 诊断入口到
后端返回并核验入口的经过时间；包含指纹计算成本，不是 CPU 时间。不包含后续
映射发布、调试符号处理和 guest 执行。新 `[steam-compile-time]` 的 `completed`
和时间覆盖**全部已录入结果**，包括 raced/failed/delivery，不能直接把它的总时间
当作五个生成分类的时间之和。

每个调用沿时间轴切换一个阶段，阶段互不重叠；各字段均为 `累计毫秒/单次调用最大毫秒`：

| 字段 | 边界与限制 |
| --- | --- |
| decode_ir_ms | GenerateIR 调用，包括解码、指纹、IR 生成和优化 |
| recheck_ms | GenerateIR 后复查 FindBlock；包含查找及内部等待，不是纯锁等待 |
| backend_ms | 后端调用进入到输出迁移前，包括临时代码生成与重试；不等同纯 CPU 时间 |
| buffer_lock_wait_ms | 实际获取 CodeBufferWriteMutex 前后；已有锁的同线程嵌套不计获取等待 |
| lookup_lock_wait_ms | 输出跟随新代，以及容量换代 ClearCache 路径中的 AcquireWriteLock 前后 |
| output_ms | 输出迁移剩余工作：buffer 更新、可能的分配、拷贝、重定位、后续缓存维护等；不含以上两处已拆出的锁等待 |
| other_ms | 诊断入口到解码前、各段间处理和结果核验；delivery 不细分，全部在此 |
| total_wall_ms | 本视图中全部完成尝试的总经过时间和单次最大值 |

累计阶段时间之和应与本行累计 `total_wall_ms` 一致，浮点打印允许舍入误差。
各阶段的 max 来自不同调用，**不能相加**。计时边界自身也有成本。
只单列明确插桩的 buffer 写锁和输出映射写锁；其他内部锁、调度等待、内存等待仍
留在其所在阶段。因此不能据 `backend_ms`、`decode_ir_ms` 或 `output_ms` 推导 CPU
占用，也不能声称已经测到所有锁等待。与热点检测的包含式计时不可直接相加。

## GenerateIR 内部分段（当前 ABI v5）

沿用同一个开关、45 秒窗口和完成事件预算。没有给每条 guest 指令增加时钟读取；
使用调用栈上的 Capture 指针传递上下文，不使用 TLS 或全局“当前编译”指针。
新 `[steam-compile-ir]` 将 `decode_ir_ms` 分成以下互斥区间：

| 字段 | 含义 |
| --- | --- |
| setup_ms | GenerateIR 入口检查、重置、CustomIR 查找及自定义 Handler；含其中的锁等待 |
| decode_ms | DecodeInstructionsAtEntry 调用 |
| build_ms | 解码返回后读取块信息、BeginFunction、指令转 IR 循环；**包含现有指纹计算**、SMC IR 构造与可能启用的反汇编输出 |
| finalize_ms | OpDispatcher::Finalize 调用 |
| pass_manager_ms | PassManager::Run 整体，包括各 pass、已有拓扑检查和定向捕获等管理工作 |
| other_ms | 其余时间：调用边界、解码器缓冲区释放、工作量记账、GenerateIR 外层 IR dump、返回处理等 |

字段格式为 `累计毫秒/单段最大毫秒/进入段次数`；例如 other 可能在一次编译中进入
多次，visits 不等于编译次数。`calls` 是已录入的 GenerateIR 调用数，`returned`
只计正常返回 IR 的调用；提前返回和 C++ 栈展开仍保留已发生的阶段时间，但被事件
预算、会话结束或诊断锁竞争丢弃的整次编译不会进入汇总。未正常退出的进程或不经过
C++ 析构的控制转移不保证提交记录。delivery 仍不细分。

`parent_ticks` 应严格等于 `accounted_ticks`，二者分别是旧 decode_ir 的整数 tick
和内部阶段 tick 之和；毫秒打印可能有舍入差异。各段最大值不能相加。所有时间都是
wall，含调度/内存等待与测量自身成本，不能解释为纯 CPU。

`[steam-compile-ir-pass]` 输出 `calls/total_wall_ms/mean_wall_ms/max_wall_ms`，
稳定名字为 `x87-stack`、`dead-flags`、`register-allocation`，以及按配置实际运行的
`validation`、`ir-dump`。未来未指定标识的 pass 归入 `other`；同类 pass 重复运行时
合并计数。pass 计时围绕实际 Run，未正常返回的栈展开也计一次，但没有输出工作量
样本。未运行的 pass 不输出。各 pass 时间已包含在 `pass_manager_ms` 中，不能再加到
GenerateIR 总时间。`pass_manager_ms - pass_sum_ms` 是管理/检查/计时边界等剩余经过
时间，不应强行归到某个优化 pass。

`[steam-compile-ir-work]` 的工作量格式为 `总量/最大单次量/样本数`：

- `decoded_instructions/decoded_blocks`：解码器已有统计，在解码正常返回后读取。
- `emitted_instructions`：到达 pass-manager 前的 TotalInstructions；CustomIR 的 1 是
  原有占位计数，不代表实际解码了一条指令，`custom` 单独报告。
- `ssa_before/ssa_after`：pass-manager 前后 `GetSSACount()` 的值，即分配的 SSA 槽位数，
  **不是存活节点数，也不直接等于优化删除或新增节点数**。该读取是 O(1)，不遍历 IR。
- 各 pass 的 `ssa_in/ssa_out` 使用相同口径。提前返回时可能只有部分工作量样本；
  必须使用各自样本数，不能一律除以 generated 或 completed。

三个新前缀输出 global、全部保留实例和线程视图。线程仍受 128 槽上限约束；除原有
最忙 8 个线程外，额外输出所有已保留且有 GenerateIR 调用的 CEF 线程，保证前 8 名
排序不会单独隐藏渲染线程。非前 8 名线程的 PID 可通过 instance 对应实例行，再与
[xp-t] 的 PID/TID 对齐；出现 thread_overflow 时仍须报告覆盖限制。

新增统计在现有完成事件的 try-lock 内汇总，不增加每个 pass 的共享锁。线程本地
Capture 内只为已进入诊断的调用初始化新增统计；关闭时不读取新增时钟，不扫描 IR。
新增每秒输出和快照复制仍有成本，快照放在报告线程堆上，避免扩大工作线程栈占用。
宿主和 WoW64/ARM64EC 使用 ABI v5 配套 magic/大小，不支持混用旧版本。

## RA 抽样分段（ABI v5）

同一开关下，每个 RA pass 实例每 64 次有效调用抽样一次，记录 setup、链校验与修复、
反向分析、正向分配、cleanup 五段。`[steam-compile-ra]` 的 `samples/returned`、阶段
时间与工作量只描述样本；`eligible` 表示已录入编译中的全部可抽样 RA 调用。
`parent_ticks == accounted_ticks` 应严格成立。日志是原 RA pass 时间的嵌套子集，
不能相加或按 64 倍当作精确全量成本。`[steam-compile-ra-work]` 沿现有扫描计数，
不额外遍历 IR；关闭或非样本不读分段时钟，但仍有条件判断开销。

`[steam-compile-ra-detail]` 增加抽样内的溢出 block、spill/fill 请求与实际 IR 发出、
常量重生成、next-use 扫描节点、合并尝试/成功计数；`[steam-compile-ra-next-use]`
记录 CalculateNextUses 调用次数及嵌套 wall 时间。它是 forward 子项，不能重复相加。

DFE 临时存储复用由独立的 `env.MADEIRA_FEX_DFE_REUSE` 控制，默认开启，精确 `0` 关闭；不依赖日志开关。容量限制、状态清理、采样边界与验收细节见
[DFE/RA 说明](steam-dfe-ra.md)。当前版本没有改变 RA 分配算法或移除安全校验。

## 代码身份、指纹与实例配额

每个 PE 初始化时取得宿主分配的唯一 instance；每个 CodeBufferManager 和每次
实际 CodeBuffer 分配取得独立序号。生成代码在持有原有写锁、最终输出缓冲区确定
后带回该缓冲区序号，以及 RX 基址、写入后的已用字节和可用容量。
guest RIP、MaxInst、32/64 位和 TF 模式参与身份。不同进程、不同管理器、单步模式
和普通模式不混合。序号和统计仅为诊断元数据，不修改翻译块布局或跳转链接。

在 GenerateIR 中遍历原有指令时，使用解码器已保存的 InstBytes，避免重新读取
可能改写/解除映射的 guest 代码。顺序、指令地址、长度和基本块边界组成形状指纹；
实际字节组成双 64 位指纹。形状不同先记 unknown，不把多块解码范围变化当成字节
变化。自定义 IR 和超过 16 KiB/2048 条指令的输入不作内容判定。哈希存在碰撞可能，
“相同”指指纹匹配，不能用这份日志作逐字节等价或安全性的证明。

ABI v2 不再共用一个 65,536 槽的历史表。PE 初始化时只读自身 PEB 中带长度的映像名，
按不区分大小写的 basename `steamwebhelper.exe` 识别目标；不按 PID、实例序号或
线程名称猜测。WoW64 与 ARM64EC 的 PE 实例仍各自独立。

- 最多 **2 个 CEF 实例，各 524,288 槽**；普通实例不能占用这些槽。
- 最多 **16 个普通实例，各 8,192 槽**；相互也不共享配额。
- 每键最多 32 次奇数步长的分散探测，不驱逐本窗口内的旧记录。
- `history_full` 是探测失败总数；每实例再拆 `probe_exhausted`（还有空槽但本次
  探测未命中）与 `capacity_exhausted`（该实例所有槽均已占用），两者之和等于
  该实例 unknown 明细中的 history_full。
- 超出实例名额记 `instance_overflow`，不借用其他实例的配额。它按无法归属的
  完成事件计数；只有 generated 且指纹和代信息有效时归入同名 unknown 原因。
  未识别为 CEF 的进程使用普通配额，须检查实际 `target` 和 `pid`。

历史存储共 1,179,648 槽，每槽 112 字节，约 126 MiB，另有不到 1 MiB 的汇总元数据。
仅首次开启时 calloc，之后永久保留；未触及的页可按需提交，实际 footprint 不等于
预留大小，但大量分散写入会显著增加驻留内存。开启日志的内存和计时开销必须实测，
不能假定无成本。默认关闭时不分配共享区。使用 epoch 隔离会话，不扫描或清空整个
历史区；旧 scope 不会写入新会话。ABI magic 和大小同时校验，宿主与两种 PE 必须
使用配套版本，不能只替换一侧。

诊断共享锁只尝试一次，竞争或嵌套重入直接丢弃并记录 `dropped`，不等待。完成
顺序倒置记 `out_of_order`，不用较旧结果覆盖较新基线。线程表有 128 槽，探测全部
槽后才报 `thread_overflow`；每秒只输出完成事件最多的 8 个线程。实例统计独立于
线程表，即使线程未输出或线程表溢出，仍能得到该实例的占用、分类和未知原因。

## buffer 换代与分类对应

`[steam-compile-buffer]` 在实际 AllocateNew 成功、替换 Latest 前记录：

- `instance/owner/previous/generation`：同一 PE、manager 下的旧新 buffer 身份；
  不要把不同 owner 或实例拼成一个代序列。
- `old_rx/old_used/old_capacity` 和 `rx/capacity`：真实地址、旧已用量与新旧可用容量，
  单位字节；capacity 为 UsableSize，不含 guard page。old_used 为当时 LatestOffset，
  不包含本次写入前可能产生的对齐填充。
- `requested`：容量判断失败时本次临时代码的字节数；对齐也会消耗余量。
- `reason=initial`：该 manager 尚无旧 buffer；`capacity`：本次代码放不下而进入
  ClearCodeCache 的路径；`explicit-or-other`：其他 StartLargerCodeBuffer 路径，
  当前插桩不进一步推断原因。初始化在 InitCore 前挂接。
- `event_t`：事件发生时距当前 session 起点的秒数；行上的 `t+` 是报告快照时间。
  `begun_marker` 只是在那一刻读到的全局开始计数，不是触发换代的编译 ticket。

事件表最多 128 条、不覆盖旧事件；`buffer_overflow` 为超限事件数，`buffer_dropped`
为诊断锁竞争导致的丢失数。事件仅表示分配成功，不记录失败分配的精确耗时或旧
buffer 的释放生命周期。关闭期间已有的 buffer 可以没有对应 allocation 事件。

`[steam-compile-generation]` 与 `scope=generation` 的分类行按
`instance + owner + generation` 对应上述事件。`used_high_water` 为成功录入的生成
事件所见最高已用量，完成乱序不会使它倒退；不是实时使用量或保留内存总量。
代统计最多 128 项，超限以 `generation_overflow` 明示，仍保留全局与实例统计。
因此可在换代前后做快照差，检验哪一代出现同内容重编译、首次观察和 unknown，
但对应关系仍不构成“可安全复用旧代码”的证明。

## 导出与分析

```text
[steam-compile-reason]       总体分类、覆盖范围、限制和最终停止原因
[steam-compile-kind]         全局每类次数、累计/平均/最大经过时间
[steam-compile-thread]       最忙 8 个线程的分类与结果
[steam-compile-instance]     全部已保留实例的 target、配额占用、探测/容量失败及结果
[steam-compile-classes]      scope=instance/generation 的五类次数与累计 wall
[steam-compile-unknown]      scope=global/instance/thread 的未知原因分解
[steam-compile-time]         scope=global/instance/thread 的互斥阶段与总 wall
[steam-compile-ir]           GenerateIR 内部互斥阶段、返回数与整数 tick 对账
[steam-compile-ir-work]      解码/发射指令数、基本块数和 SSA 分配槽位
[steam-compile-ir-pass]      各 pass 次数、累计/平均/最大 wall 和输入输出槽位
[steam-compile-ra]           RA 样本调用的互斥阶段、样本数与整数 tick 对账
[steam-compile-ra-work]      RA 样本的 SSA 槽位、块数、两遍节点数与可疑块数
[steam-compile-generation]   实际输出 buffer 的身份、容量与已用高水位
[steam-compile-buffer]       实际分配事件、容量触发与旧新代对应
```

同一 session 每秒输出累计快照，使用最后一份完整快照或两个快照之差，不能逐秒
相加。总数、实例、线程和代明细是相同事件的不同视图，也不能相加。buffer 事件
随快照重复输出，按 `session + event` 去重，再使用 `event_t` 对齐其他性能日志。
`snapshot=busy` 是漏掉这一轮输出，不代表计数清零。先确认 attached_paths
（位 1=WoW64、位 2=ARM64EC）、target、各实例占用及 unknown 原因，再判断比例。
同时检查 dropped、thread_overflow、instance_overflow、generation_overflow、
buffer_dropped、buffer_overflow；没有输出不能解释为数值为零。

## 下一次实机验收

建议同时开启轻量性能日志，保持前台运行约 50 秒后导出同一次日志，保持操作脚本
一致。先检查是否正常 duration-complete，是否提前碰到 400,000 次事件预算。

1. 用 `[xp-t]` 确认真正的 CEF 渲染线程 PID/TID，再查对应实例 `target=cef`。要求
   在编译高峰前后都能输出该线程，逐区间报告 unknown/generated，不能只看整体平均。
2. 首先以 CEF history_full 导致的 unknown 低于 1% 为覆盖目标；这是待验证目标，
   不是当前实机保证。其他未知原因单独报告，不通过扩大表掩盖。普通实例溢出不应
   改变 CEF 的配额占用。若超过两个 CEF 实例，先处理实例名额不足。
3. 检查每个视图五类之和等于 generated；unknown 原因之和等于 unknown；互斥阶段
   累计之和等于本视图总 wall。用锁等待、decode/IR、backend/output 的区间增量定位
   编译峰值，不从线程 CPU 中直接减去 wall。
4. 按实例/manager/代号连接 buffer 事件和分类增量；确认 capacity 事件的旧余量、
   requested 和对齐能解释换代，再比较新代的 first/new-generation/unknown 成本。
5. 用相同操作比较诊断关闭/开启时的 CPU、footprint、窗口排队及事件丢失率，量化
   这次扩大历史表和增加时钟读取的成本。

6. 用新 `[steam-compile-ir]` 检查 global、目标实例及渲染线程的 `parent_ticks` 等于
   `accounted_ticks`，检查 `pass_sum_ms <= pass_manager_ms`（允许打印舍入误差）。
   对编译高峰做累计差，分别列出各阶段总时间和各 pass 总时间、调用次数、平均值。
   阶段平均值用总时间/visits；整体 GenerateIR 平均值用 decode_ir_ms/calls，不能混用。
7. 结合 `[steam-compile-ir-work]` 与各 pass 的输入样本数判断是调用增多、输入变大，
   还是单位输入处理更贵；报告提前返回以及普通实例/线程覆盖丢失。暂时只得到分配
   槽位规模，不能把前后差值写成实际删掉的 IR 节点数。
8. 固定 Steam 启动和交互脚本，分别采集开关开/关的 CPU、footprint、窗口排队。
   开关对照衡量整个诊断的开销；本次没有独立指纹开关，不能从对照中单独算出指纹成本。
   45 秒之后的编译仍不在该窗口内；本任务没有修改窗口或提高事件预算。

GitHub Actions 的受控 fixture 覆盖配额隔离、分段覆盖率、探测溢出、不驱逐、
分类/阶段对账、并发/会话隔离、buffer 事件边界和 patch-chain；新增用例覆盖内部阶段
与父计时对账、pass 正常/未完成返回、工作量汇总、关闭/会话隔离、CEF 线程跌出前 8 名
后的输出，以及原生 no-op 接口。它不能代替完整 FEX PE 编译链接及实机验证。
代码修改本身不表示这些检查已经执行或通过。
