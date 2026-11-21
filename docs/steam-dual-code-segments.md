# Steam CEF 双代码段（实验）

在 **Steam 设置 → 高级 → 性能** 中打开 **CEF 双段代码缓存（实验性）**，下次启动 Steam 生效。开关读写原有的 `env.MADEIRA_FEX_DUAL_CODE_SEGMENTS` 配置，手动设置的值也会反映在界面上。默认关闭，仅针对识别出的 `steamwebhelper.exe`（WoW64 或 ARM64EC），独立于编译原因日志。关闭并重启可回退；若同时启用 PreviousCode，双段模式实际启用时优先，不运行旧代迁移。未能验证 JIT 池区间、启用了代码缓存序列化/校验或全局 JIT 命名时，不启用双段。

同页的 **CEF 旧缓存主动迁移（实验性）** 默认关闭，保存到 `env.MADEIRA_FEX_DUAL_OWNER_MIGRATION`，下次启动 Steam 生效。WoW64 CEF 实际启用双段模式且允许系统调用停驻时，仍占用旧缓存组的线程可以在安全的系统调用边界上切换到新组。最后一个引用释放后，128 MiB 追加额度可以再次使用。

## 分配、查找和回退

- 保持原 `CodeBuffer` 为逻辑所有者，仍只有一张 L3 和一份反向 guest 页索引。主段初始容量和增长规则不变，第二段不预分配。主段装不下当前翻译时，普通 emitter writer 才能尝试经既有 EC_CODE 分配器申请一次 128 MiB。沿用池余量约束，不改 A/B、C 的边界或 headroom，不减半重试，不接受池外地址。第二段预留同样的不可发射尾页；iOS 池 carve 的 OS 保护页仍是尽力设置，不作为安全边界。
- 成功追加后只把新翻译写入第二段，使用独立写游标并保留 RX/RW 偏移；不切换 `Latest`、不换 L3、不清 L1/L2 或 call/ret，也不发起旧代线程扫迁。L3 条目记录物理段，旧段的有效条目仍通过原查找路径命中，不需要回切整个线程。分派器能在同一张表命中任一段。
- 同段可照常链接。直接分支的 linker 在既有锁下重新核对目标地址和段标签，拒绝跨段或过期目标；间接分支的已命中 L1 路径也检查源/目标是否在唯一第二段内，跨段走现有分派器。这个实验会给间接 L1 命中增加指令，收益不能仅从少编译次数推断。iOS 原来禁用的 RET 预测捷径不恢复。
- 每个 PE 模块最多有一个额外的物理段（包括已退休但仍持有引用的组），每段不超过 128 MiB。超出可用容量、额度已占用、申请失败或第二段也满，回退到原换代流程；不逐条回收代码块、不在返回地址仍可能有效时复用旧地址。嵌套/未发布异常投递不执行追加，未发布投递仍遵循原来禁止换代的规则。

## 失效与生命周期

自修改、卸载和权限变化仍走原有 guest 页索引和整个存活缓冲区的失效遍历，两段没有独立映射或额外有效期；入链仍由原 `Erase` 拆除。主段与第二段同属一个 `CodeBuffer`。线程的 `CurrentCodeBuffer` 和异常返回的 `SignalHandlerCodeBuffers` 引用保护整个组，PC 识别覆盖两个可用代码区，排除保留尾页。最后一个引用释放后才归还第二段和额度；新组即使拿到相同 VA 也用新的物理 ID。换代以后的旧组可能按原规则继续短暂执行，但不存在新增长期可查的第三段。

## 验证与日志

- `[fex-segments] mode=dual` 表示本模块启用，并不表示已分配；`append=added` 才表示第二段已接入。`extra-budget`、`alloc-failed`、`too-large`、`second-full` 分别表明相应回退。追加尝试日志有条数上限。
- WoW64 的启动日志用 `owner-migration=on` 或 `off` 显示开关状态。`event=owner-migrated` 表示某个线程已在系统调用边界切换，`event=released` 表示旧组的追加额度已归还。
- `[fex-segments] append=extra-budget` 的 `request_*` 是尝试追加的新组，`budget_*` 指当时可读到的额度持有者。用 PID、manager owner、第二段 generation 关联 `[fex-segment-budget] event=reference-snapshot` 和 `event=released`。若分配或释放时序使额度持有者不可读，`budget_generation=0`。
- `reference-snapshot` 在现有换代扫描中记录匹配该组的线程当前引用 `current_refs`、异常保留引用 `signal_refs` 和持有异常引用的线程数 `signal_threads`。`busy` 是未取得线程迁移锁的数量，另列扫描的 `in_sim`、`sig_pin` 等全组迁移结果。各线程逐个采集，范围限已登记线程和调用者，临时编译引用及管理器引用不在两项计数中。`released` 在映射释放调用返回、额度归还后输出。双段模式启用时自动记录。
- `event=reference-holder` 只列出扫描后确认仍引用退役组的线程，记录 Windows `tid`、该线程在本轮的 `in_sim` 和 `scan_result`。例如 `in-sim` 是扫描时仍在执行翻译代码，`signal-pinned` 是迁移检查发现异常上下文仍在使用，`raced` 是迁移检查期间状态已变动。`caller` 表示当前扫描发起者，原扫描跳过自身，因此 `in_sim=-1`。按 `pid`、`owner`、`generation`、`sweep_gen` 和 `retry_left` 与汇总关联。每次快照最多输出 8 个持有者，`holders_omitted` 列出仍有多少已确认持有者未单独打印。无法取得迁移锁的线程仍计入 `busy`。
- 编译原因日志 ABI v7 中 `reason=segment-append` 表示物理输出段切换，**不是**清表或旧代线程迁移；`reason=capacity` 仍表示传统换代。`generation` 字段标记本次实际输出的物理段，不是逻辑 L3 的数量，也不证明旧条目都可安全复用。
- Actions runtime 夹具覆盖真实辅助头的延迟分配、边界、失败、预算、持有引用与同 VA 再分配。它执行实际 L3 方法体，检查两段能在同表命中、一个 guest 页能同时使两段条目及入链失效、重编译后不再认旧地址，并核对生产补丁的发射、链接和异常接线。夹具不替代 iPad 上的 SMC、卸载、权限切换、异常返回与换代压力验证。真机收益应比较同负载的 CEF 渲染线程编译峰值、首帧/交互时间及 JIT 池占用，不能只比较追加次数。
