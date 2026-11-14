# DFE 临时存储复用与 RA 抽样诊断

本改动属于 mdeck 自有补丁 `0006-dfe-scratch-ra-sampling.patch`；不修改 FEX
子模块 pin，不向上游贡献。DFE 优化不依赖诊断开关；RA 新统计沿用“编译原因日志”，
默认关闭。未改变任何 pass 的运行顺序，也未改变代码缓存大小或跨代复用策略。

## DFE：复用空存储，不复用分析结果

原来每次 Run 都新建 CFG/工作队列，每个基本块先 `reserve(2)` 前驱槽，再新建
Seen 校验数组。现在每个 pass 实例保存自己的 `DFEScratch`：

- CFG 的 BlockMap 仍按本次 BlockCount 精确 resize；不能把上次较大的范围当作
  有效 ID。缩小时会销毁尾部基本块及它们的前驱存储，避免保留无效块。
- 保留仍存在的前驱 vector 容量；只有该块真正收到第一条边、且容量不足 2 时才
  reserve(2)。无前驱块不再为两个空槽单独分配。
- 重用 Seen 数组容量，每次仍完整 assign 为 0。CFG 的 sentinel、错误计数和
  每次预算保持局部变量；flags 与 InWorklist 仍按原逻辑初始化。
- 工作队列继续使用原 deque，初始 push_back、重排 push_front、取 pop_back 的
  顺序不变。deque 自身仍可能分配/释放分段，不宣称整个 pass 零分配。
- Lease 析构在正常返回、提前返回及 C++ 异常展开时清除所有旧 Node 指针、前驱
  内容、flags、工作队列和 Seen 内容，只留下可用容量。嵌套调用借用独立 fallback，
  不覆盖外层正在使用的 IR。pass 本来按编译线程持有，未增加跨线程共享或新锁。
- 保留上限按容量而非 size 计算：BlockMap/Seen 各 4096 个元素，所有当前块前驱
  capacity 合计 16384 个 uint32。超过时在退出释放对应 vector 存储；不是限制
  可编译块数。deque 的内部 map/分段缓存仍由标准库管理，以上不是总 RSS 上限。

收集边、前驱校验与 digest、坏 ID sentinel、每次 pop 校验、传播预算、反向链
保护、flag 传播、分支折叠和 parity 优化均保留。新的清理不能回滚一次异常传播
已完成的 IR 修改；保留原保护的边界，不把“提前退出”解释成无条件恢复原 IR。

此方案减少可见的重复分配，但尚未实测节省比例。清理也有成本；输入尺寸波动、
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

两类日志沿用现有 45 秒窗口、事件预算、try-lock 丢弃与线程容量限制。eligible 是
已录入编译中的 RA 调用，不包含整个完成事件被丢弃的调用。returned 只计正常完成
的样本；C++ 展开保留部分时间，不保证覆盖进程死亡或绕过析构的非局部退出。

## 验证与实机判定

所有用例仅通过 GitHub Actions 执行，本轮未运行本地测试或构建。

- `check-dfe-scratch.py` 在临时副本应用补丁，提取真实前后 CFG 编译为 ASAN/UBSAN
  fixture，比较边顺序、digest、sentinel 和工作队列轨迹；计数分配器检查同尺寸
  热存储不重复分配 BlockMap/前驱/Seen，覆盖变大变小、嵌套、异常退出、容量释放。
  同时要求原分析/IR 重写函数和传播/恢复代码保持逐字一致。这不是 guest IR 执行测试。
- `check-steam-compile-reasons.py` 增加 RA stride、正常/未完成样本、阶段对账、默认
  关闭、跨实例汇总、旧 epoch 丢弃及宿主格式用例；原完整补丁链检查继续覆盖所有补丁。
- 完整 FEX PE 编译/链接、真实 Steam 页面与游戏正确性，以及设备上的净收益仍需
  后续授权构建后验收。不要由 fixture 的分配次数直接推导 App 性能提升。

下一份实机日志先看 DFE 每调用时间并结合 SSA/块数和 CPU 频率；RA 同时查看样本数量、
输入大小、check/reverse/forward 占比及 suspect_blocks。抽样可能与周期性工作相关，
不能仅凭稀疏样本删除安全校验。只有相近输入下持续下降，且未增加错误或运行时成本，
才能判断 DFE 优化有效。
