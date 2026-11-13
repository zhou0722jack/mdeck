# ARM64EC 与 WoW64 共用 C 区

## 改动范围

此前 `virtual_ios.c` 通过 `!ios_wow_base()` 将 WoW64 排除在 C 区代码缓冲区分配之外，因为 WoW64 的 FEX 分配器只接受 `WINE_IOS_JIT_RX/SIZE` 所描述的主池范围。即使 C 区仍有空间，32 位 CEF 也只能使用主池尾部。设备日志中请求 128 MB、降级到 16 MB 的现象是排查起点；改动本身尚不能证明卡顿已经改善。

现在两条路径都可以使用已验证的 C 区，仍按可用已释放块、C 区新块、主池尾部的顺序处理；C 区不足时继续执行原有尾部预算和降级策略。A/B/C 的申请容量、Windows 主程序预留窗口、原生映射孔洞均保持原有布局。

FEX 修改作为 mdeck 专用补丁 `build/fex-patches/0002-ios-wow64-region-c.patch` 保存，沿用仓库已有补丁机制，子模块的上游版本不变。Windows runtime 的输入键已经包含 `build/fex-patches/**`，下次明确请求构建时会重新生成匹配补丁的 `xtajit.dll` 和 `xtajit64.dll`。

## 地址与映射校验

- 主池和 C 区各自维护独立 RX 范围；一次分配必须完整位于其中之一，不能跨越 C、Windows 主程序窗口和主池。
- WoW64 初始化在 `InitCore()` 发射代码之前解析 `WINE_IOS_JIT_TAIL_REGION`。C 区声明要求完整的十六进制 `base:size`、16 KB 对齐、至少 16 MB、位于 4 GB 以上且完全低于主池，并验证共享 RX→RW 偏移计算不会溢出或下溢。
- 未声明 C 时保留仅主池行为；非空但非法的 C 声明在初始化阶段报告错误并停止，避免部分初始化后才发现映射不一致。
- WoW64 的执行分配检查继续拒绝普通内存、RW 地址、跨边界范围和整数溢出。分配失败时沿用释放后返回空值的行为。
- ARM64EC 和 WoW64 的原子访问地址转换都识别 C，且检查整个访问长度；主池/C 以外仍沿用已有匿名别名解析。
- C 区的执行权限、RW/RX 写入读回、释放、复用、信号与 Mach 异常地址分类继续使用现有实现。`check-pool-low.py` 检查这些关联入口。

## GitHub Actions 与验收边界

现有 `Build IPA` workflow 的手动参数 `build_ipa` 默认关闭。自动 push/PR 和手动关闭该参数的运行只执行 `plan` 中的检查；`reuse`、`llvm`、`fex`、`i386`、`runtime` 和 `app` 均要求明确的手动 `build_ipa=true`。检查与构建使用不同并发组，检查不会取消已授权的构建。

针对性检查在 GitHub Actions 中把补丁应用到固定源文件的临时副本，编译并执行生产区域校验、实际分配器入口和原子别名函数，覆盖 WoW64/ARM64EC 两个编译分支及 C 存在/缺失两种情况，并使用 ASan/UBSan；宿主的 C 区辅助函数和原有地址分类入口一并检查。测试不执行 Wine，也不生成正式运行库或 IPA。

完整 xtajit PE 编译、iPad 上实际执行 C 区代码、Steam/CEF 稳定性、缓存代切换次数与性能改善仍需后续构建和真机验收。用户未明确要求构建时，不执行这些产品构建步骤。
