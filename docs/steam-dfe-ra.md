# DFE 临时存储复用与 RA 抽样诊断

本改动属于 mdeck 自有补丁 `0006-dfe-scratch-ra-sampling.patch`；不修改 FEX
子模块 pin，不向上游贡献。DFE 优化不依赖诊断开关；RA 新统计沿用“编译原因日志”，
默认关闭。未改变任何 pass 的运行顺序，也未改变代码缓存大小或跨代复用策略。

## 独立 DFE 优化开关

位置：**Steam 设置 → 高级 → 性能 → DFE 临时存储复用**。
默认开启，保持 Build 41 的优化行为；对应配置 `env.MADEIRA_FEX_DFE_REUSE`。
精确 `0` 关闭，缺省或其他值开启；界面始终写 `1` 或 `0`。Steam 全局 profile
优先于全局 madeira.cfg，跟随该 profile 的 Steam 游戏继承此选择。

更改在下一次启动 Steam 时生效，运行/启动中禁用此设置。每次会话先清除上一次
进程环境中的该项，再应用本次配置；两条 PE 路径在 InitCore 前固定策略，并打印
`[fex-dfe] path=wow64|arm64ec mode=reuse|legacy`。策略不依赖编译原因日志是否开启，
pass 创建后不会切换存储策略。缺省首次读取也固定为开启，避免迟到配置改变已有 pass。

- **开启**：使用下述按 pass 实例复用容量、按实际边分配前驱槽的路径。
- **关闭**：每次 Run 使用独立的新容器，不保留容量，也不构造闲置缓存 deque；
  恢复每个 block 的 `reserve(2)`，Seen 使用校验作用域内的局部数组。
  临时容器正常析构，不额外遍历清理所有 block。恢复的是原分配策略，
  两个模式共用相同的 CFG 校验和 flag 传播/改写逻辑。

RA 分段与细项仍由“编译原因日志”控制；缓存查找优化仍是另一独立开关。
对比时保持这些诊断设置一致，只切换 DFE 选项，并从启动日志核对实际模式。

## DFE：复用空存储，不复用分析结果

原来每次 Run 都新建 CFG/工作队列，每个基本块先 `reserve(2)` 前驱槽，再新建
Seen 校验数组。开启后，每个 pass 实例按需创建自己的 `DFEScratch` 存储：

- CFG 的 BlockMap 仍按本次 BlockCount 精确 resize；不能把上次较大的范围当作
  有效 ID。缩小时会销毁尾部基本块及它们的前驱存储，避免保留无效块。
- 保留仍存在的前驱 vector 容量；只有该块真正收到第一条边、且容量不足 2 时才
  reserve(2)。无前驱块不再为两个空槽单独分配。
- 重用 Seen 数组容量，每次仍完整 assign 为 0。CFG 的 sentinel、错误计数和
  每次预算保持局部变量；flags 与 InWorklist 仍按原逻辑初始化。
- 工作队列继续使用原 deque，初始 push_back、重排 push_front、取 pop_back 的
  顺序不变。deque 自身仍可能分配/释放分段，不宣称整个 pass 零分配。
- 复用 Lease 析构在正常返回、提前返回及 C++ 异常展开时清除所有旧 Node 指针、前驱
  内容、flags、工作队列和 Seen 内容，只留下可用容量。嵌套调用借用独立 fallback，
  退出直接销毁，不覆盖外层正在使用的 IR。pass 本来按编译线程持有，未增加跨线程共享或新锁。
- 保留上限按容量而非 size 计算：BlockMap/Seen 各 4096 个元素，所有当前块前驱
  capacity 合计 16384 个 uint32。超过时在退出释放对应 vector 存储；不是限制
  可编译块数。deque 的内部 map/分段缓存仍由标准库管理，以上不是总 RSS 上限。

收集边、前驱校验与 digest、坏 ID sentinel、每次 pop 校验、传播预算、反向链
保护、flag 传播、分支折叠和 parity 优化均保留。新的清理不能回滚一次异常传播
已完成的 IR 修改；保留原保护的边界，不把“提前退出”解释成无条件恢复原 IR。

此前设备日志支持此方案降低 DFE 单次耗时，但尚无严格受控的开关对照结果。清理也有成本；输入尺寸波动、
超过保留上限和分配器行为都会影响收益。

## RA：先定位扫描成本

`0005` 通过显式 `RunWithReason` 调用传递栈上的 Capture；普通 pass 默认转发原 Run。
RA 算法、链修复、溢出与寄存器分配顺序未变。每个 RA pass 实例有独立序号，只在
编译原因日志有效时推进；第 1、65、129……次调用采样，即 stride=64。序号跨诊断
窗口延续，首个样本不保证在窗口第一个调用；不能按小区间严格乘 64 外推。

一个被采样的调用从头到尾计时，内部划分：

| 阶段 | 边界 |
| --- | --- |
| setup | Run 入口、数组 resize 与每个块的寄存器可用状态初始化 |
| check | IRTopoNoteChecked、QuickBackwardOK，以及必要的 HandleSuspectBlock 诊断/修复 |
| reverse | 原反向 kill-bit/SRA 分析，含预算保护；不安全时仍按原逻辑跳过 |
| forward | 原正向分配、spill/fill、合并与块尾一致性检查 |
| cleanup | 最终数组 clear、PostRA 标志及正常退出记账 |

阶段时钟只在边界读取，不逐节点读时钟，也不新增 IR 遍历。节点计数沿已有循环，
只对样本累积；非样本仍有轻量条件判断，不能宣称默认关闭完全零指令开销。
计时为 wall，包含调度等待、内存等待、计时和统计成本。

`[steam-compile-ra]` 按 global/instance/thread 输出 eligible、samples、returned、
stride、total_wall_ms、max_wall_ms、parent_ticks/accounted_ticks，以及各阶段
`累计毫秒/单个样本调用最大毫秒`。各块同阶段会在一次样本调用内相加再更新 max，
不等于单块最大。整数 parent_ticks 必须等于五阶段之和。它是完整 RA pass 的
**抽样子集**，不能加回 RA/GenerateIR 总时间，也不能直接拿抽样时间除以全量调用数。

`[steam-compile-ra-work]` 为 `总量/单样本最大/样本数`：SSA 已分配槽位、处理的块数、
反向和正向实际循环节点数、进入 HandleSuspectBlock 的块数。反向预算失败的那次
未处理节点不计入；正向包括随后因 trivial/inline 等原因跳过的迭代，新增/删除 IR
会使两遍节点数不同。没有单独统计 validator 的节点数，不把块数当成遍历节点数。

这些日志沿用现有 45 秒窗口、事件预算、try-lock 丢弃与线程容量限制。eligible 是
已录入编译中的 RA 调用，不包含整个完成事件被丢弃的调用。returned 只计正常完成
的样本；C++ 展开保留部分时间，不保证覆盖进程死亡或绕过析构的非局部退出。

## RA 正向细项（ABI v5）

沿用同一批 stride=64 样本，没有新增采样开关或延长窗口。
`[steam-compile-ra-detail]` 同样按 global/instance/thread 输出，工作量字段均为
`总量/单个 RA 样本最大量/RA 样本数`，没有发生操作的样本也计入分母：

| 字段 | 口径 |
| --- | --- |
| spilled_blocks | 至少进入一次 SpillReg 的基本块数；包括只释放已溢出值或可重生成常量的情况，不等于实际写栈块数 |
| spill_requests | SpillReg 进入次数，同一块可多次 |
| spills | 成功生成 `_SpillRegister` IR 的次数；已溢出值和常量不会重复计入 |
| fill_requests | InsertFill 进入次数 |
| fills | 成功生成 `_FillRegister` IR 的次数 |
| remats | InsertFill 中成功重生成常量的次数，与 fills 分开 |
| next_use_nodes | CalculateNextUses 原有循环实际检查的节点数，包含触及 Until 时用于终止判断的那个节点；不增加遍历 |
| merge_attempts | 实际调用 TryPostRAMerge 的次数；LastNode 为空、trivial 指令等跳过路径不计入 |
| merge_successes | TryPostRAMerge 正常返回 true 的次数；不等于删除节点总量 |

`[steam-compile-ra-next-use]` 单列 CalculateNextUses 的 `calls`、正常结束的
`returned`，以及 `total_wall_ms/mean_wall_ms/max_wall_ms`。最大值按**一次扫描**，
不同于工作量行的“单个 RA 样本最大量”。计时包含 SourcesNextUses 清理、NextUses
resize、整个原有反向扫描和 SourceIndex 设置；每次扫描仅在入口与出口读时钟。
它已经包含在 RA 的 forward 时间内，**不能再加回 forward、RA 或 GenerateIR**。

扫描采用栈上 RAII：正常完成和 C++ 异常展开都计入 calls/时间，returned 只计正常完成；
非局部退出或进程结束仍不保证记录。spill/fill 计数表示编译期间发出的 IR，不是
运行时内存访问数，也不直接等于最终机器指令数。异常中断时 fill_requests 可以大于
fills + remats，merge_attempts 也包括尚未正常返回的尝试。

所有计数和扫描时钟仅对抽样调用生效。非样本/关闭时仍有条件判断；未新增共享锁、
TLS、IR 遍历或逐节点时钟。扫描时间为 wall，包含调度等待和测量开销。固定步长
抽样可能有偏差，不能把这些计数或时间简单乘 64 当作全量结果。

## 验证与实机判定

所有用例仅通过 GitHub Actions 执行，本轮未运行本地测试或构建。

- `check-dfe-scratch.py` 在临时副本应用补丁，提取真实前后 CFG 编译为 ASAN/UBSAN
  fixture，比较边顺序、digest、sentinel 和工作队列轨迹；计数分配器检查同尺寸
  热存储不重复分配 BlockMap/前驱/Seen，覆盖变大变小、嵌套、异常退出、容量释放。
  同时要求原分析/IR 重写函数和传播/恢复代码保持逐字一致。这不是 guest IR 执行测试。
- `check-steam-compile-reasons.py` 增加 RA stride、正常/未完成样本、阶段对账、默认
  关闭、跨实例汇总、旧 epoch 丢弃及宿主格式用例；原完整补丁链检查继续覆盖所有补丁。
  新细项用例检查请求数与实际发出次数分开、正常和异常扫描、扫描计时嵌套、合并计数、
  非样本无计数以及原生无 PE 依赖。调用点契约检查覆盖三条 AssignReg 路径和扫描边界；
  这些检查不等价于实际执行完整 RA 算法或 Steam 正确性验证。
- 完整 FEX PE 编译/链接、真实 Steam 页面与游戏正确性，以及设备上的净收益仍需
  后续授权构建后验收。不要由 fixture 的分配次数直接推导 App 性能提升。

下一份实机日志先看 DFE 每调用时间并结合 SSA/块数和 CPU 频率；RA 同时查看样本数量、
输入大小、check/reverse/forward 占比及 suspect_blocks。抽样可能与周期性工作相关，
不能仅凭稀疏样本删除安全校验。只有相近输入下持续下降，且未增加错误或运行时成本，
才能判断 DFE 优化有效。

独立开关用例（仅 Actions 执行）另覆盖：默认/显式 0/1 和首次读取策略冻结，
两种模式的真实 CFG 边顺序/digest/sentinel 一致性，关闭时每次重新分配及异常析构，
未启用复用时不创建缓存 deque，配置继承/覆盖/去重、与诊断开关独立、两条 PE
路径先于 InitCore 初始化、会话环境重置和中文界面。新增用例尚未执行；静态审查
不能代替完整 FEX 编译与实机对比。
