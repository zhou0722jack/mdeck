# 编译前端局部快路径

mdeck 自有 `0008-compile-front-end-fast-paths.patch`，叠加在 0001–0007 后。
不修改 FEX 子模块或 pin，不向上游提交。此补丁不增加诊断输出或新的设置，
不依赖编译原因日志；三个改动会应用于使用这些代码的翻译实例，不仅是 CEF。
已有尚未打包的 DFE 活动视图/保留存储分离改动仍在 0006 中。

## RA：普通路径提前拒绝寄存器不匹配

原 TryPostRAMerge 无条件读取 LastNode 的 IR op，然后依次尝试特殊改写，
最后才检查普通移动合并的两个目的寄存器是否相等。
现在先按当前 opcode 分流：

- PUSH、POP、DIV、UDIV、XGETBV、CPUID 继续执行原函数路径，不提前检查目的寄存器。
- 其他 opcode 若两目的寄存器不匹配，直接返回 false，避免读取 LastOp 和特殊分支检查。
- 寄存器匹配时继续原逻辑；KillMove、参数重写、调用顺序和短路条件保持原样。

所有特殊 opcode 都保留原路径，包括尺寸不满足改写条件的情况。CPUID/XGETBV
以及部分除法改写可能改变 IR 却返回 false，不能依据低 true 比率跳过它们。
提前拒绝仍记录原有 reg-mismatch 采样类别，不添加新的计数类别、不剪掉 merge 调用。

这减少了普通失败路径的工作，但也增加 opcode 分流；总 RA wall/CPU 是否下降需要设备验证。

## Decode：已访问地址集合保留连续存储

只把私有 `VisitedBlocks` 从 `fextl::set<uint64_t>` 改成基于项目现有
`fextl::robin_set<uint64_t>` 的 VisitedSet。实际实现为固定版本 ankerl::unordered_dense，
并不新增依赖。该集合只使用 clear、size、contains、insert/emplace；没有按顺序
遍历、取最小值或向外暴露迭代器的调用。

- 成员、重复地址和清空语义不变。clear 保留值数组和哈希桶容量，减少每个访问地址的树节点分配。
- `BlocksToDecode` 和 `CurrentBlockTargets` 保持有序 set，最小目标选取和 merge 顺序不变。
- EntryPoints、CodePages、块分割、SMC 检查与地址域转换均未更改。
- 若桶数大于 8192，下一次 clear 用空集合交换，释放那次大解码留下的容量。
  因此超限存储可以保留到下一次解码入口或 Decoder 析构；不是本次解码分配上限。
  阈值按 bucket 数计，不是元素数或总字节数。正常 clear 会清理桶，其工作量与保留容量有关。
- 只保留存储，不复用上一轮“已访问”结果；每次解码入口仍清空全部成员。

此改动未声称所有 Decode 临时对象都已池化；有序集合仍可能分配节点，固定解码池未改变。

## IR：复用直接跳转已经找到的目标

JUMPOp 的 multiblock 路径原来先 `JumpTargets.find(TargetRIP)`，命中后通过
GetNewJumpBlock 再查找同一个 RIP。现在直接传入已找到的 `BlockEntry`。
两次查询之间原本没有修改目标表，所以使用当前 iterator 不引入跨调用缓存或新生命周期。

目标缺失时的退出块构造、相对地址/32 位环绕、deferred flags、寄存器刷新和
multiblock 关闭路径都保持不变。每个命中的该类跳转减少一次查询，收益范围仅限这一调用点。

## 验证与限制

新增 Actions-only `tests/host/check-compile-front-fastpaths.py`，注册到 runtime 检查组：

- 应用完整补丁链并逐个检查可逆上下文，保留已有 DFE 检查。
- 从应用后的源码提取完整的修改前/后 TryPostRAMerge 函数体；受控 IR/CPUID/emitter
  适配器对比返回值、IR 字段、emit 调用、常量寄存器、KillMove 调用和采样分类，
  覆盖特殊改写和 false-with-rewrite，并确认普通失败减少 LastOp 读取。
- 使用实际 VisitedSet 类和项目固定版本的 unordered_dense，对照 std::set 的成员语义，
  覆盖 64 位地址、重复地址、清空、异常后重用及实例隔离；计数分配器检查热身后
  2048 个元素反复使用不再分配、超限桶在 clear 后释放。
- 提取实际直接跳转分支，比较目标存在/不存在及 multiblock 开关的行为，并检查
  命中时查询从两次变为一次；其余 OpcodeDispatcher.cpp 内容要求逐字不变。
- 计划在 O0/O2 + ASAN/UBSAN 下运行。适配器不执行真实 guest IR，也不是完整 FEX/PE 编译。

本轮仅完成源码和静态核查，没有运行本地测试、构建或 Actions；也未生成 IPA。
实机验收需先确认 Steam 正常启动、相同操作没有新增异常，再比较同诊断配置下的
Decode wall、RA wall、renderer CPU、整体 CPU 和启动耗时。不能把各阶段 wall 相加到
CPU 时间，也不能从减少查询或分配直接推算整机加速比例。
