# Steam Win64 CEF 126：对齐预留与重复启动

## 实际版本与申请序列

官方 Win64 清单版本 `1792618285` 所引用的
`bins_cef_win64.zip.0bad5abe29375d80e5bb0eedf714329369140164` 中，
`bin/cef/cef.win64/chrome_elf.dll` 的文件版本为 **126.0.6478.183**，
大小 1,405,592 字节，SHA-256：
`6358830f96f36efa7516b3277cf69c1f132f97d4d93c365ccf061a7cf11e1e39`。
2026-11-08 从 Valve CDN 读取中央目录与对应成员，解压后检查了版本和映像。

此前将日志里的 32 GB 一概解释为新版 Chromium 的长期 glued pool 不够准确。
本版本的日志序列与未粘连的普通池、带 forbidden zone 的 BRP 池一致：

1. 16 GB、16 GB 对齐的随机地址提示失败；这些提示远高于设备地址上限。
2. 分配约 32 GB 的临时范围，释放后在 `0x7400000000` 保留 16 GB 普通池。
3. 再申请 16 GB + 64 KiB、基址对 16 GB 取模为 `16 GB - 64 KiB` 的范围。
4. 随机提示失败后的额外 32 GB 对齐探测找不到连续空间，`chrome_elf.dll` 初始化中止。

对应源码见固定版本的
[PartitionAddressSpace::Init](https://github.com/chromium/chromium/blob/126.0.6478.183/base/allocator/partition_allocator/src/partition_alloc/partition_address_space.cc)
和 [AllocPagesWithAlignOffset](https://github.com/chromium/chromium/blob/126.0.6478.183/base/allocator/partition_allocator/src/partition_alloc/page_allocator.cc)。
Chromium 126 的普通池和 BRP 池可以分别预留，BRP 池前多留一个 Windows 分配粒度的保护区；
不需要把其所有 32 GB 探测都当成必须永久保留的池。

`madeira-log 13.txt` 第 13045 行为临时范围，第 13051 行释放它，第 13056 行为 16 GB 普通池，
随后 16 GB + 64 KiB 提示失败并进入 32 GB 探测。第 15374、15482、15483 行为最终失败与退出。

## 全额预留的放置修正

只对固定客户端路径下的 **64 位** `cef.win64/steamwebhelper.exe` 生效。
映射到该进程的模块还必须匹配上述 `chrome_elf.dll` 的 PE 架构、时间戳、SizeOfImage，
以及两个与重定位无关的代码指纹。未知版本、其他进程和其他启动代次不使用此路径。
映射器只将完整的 `chrome_elf.dll` 交给身份检查；未知版本和真实范围被占用分别记录
`build not recognized`、`full-size pool candidate unavailable`，不静默声称适配已启用。

对该版本已知的两种超出设备地址上限的随机提示，直接尝试完整的、相邻但不重叠的实际范围：

| 用途 | 实际范围 | 大小 |
|---|---|---|
| 带保护区的池 | `[0x73ffff0000, 0x7800000000)` | 16 GB + 64 KiB |
| 普通池 | `[0x7800000000, 0x7c00000000)` | 16 GB |
| 既有 FEX 地址区 | 从 `0x7c00000000` 开始 | 不占用、不移动 |

普通池先放上方，给随后带保护区的池留下完整下方范围。带保护区的基址加 64 KiB 后，
仍然为 16 GB 对齐。后端使用 Wine 自己的 fixed-address reserve，保持原来的大小与保护权限；
不覆盖已有映射、不缩短申请、不生成软预留。后端失败时不报告成功，继续原来的失败路径。
设备地址范围内的固定地址请求、MEM_COMMIT、其他权限和其他尺寸均不改动。

这个修正处理日志里**第一次阻止 chrome_elf 初始化的对齐分配**。
并不证明此后 libcef/V8 的所有预留和渲染都能完成。若出现新的容量故障，需要下一阶段日志定位；
不会为通过初始化而把未取得的内存伪装为已取得。

## 失败处理

同时记录该进程 16–32 GB 预留的真实 `STATUS_NO_MEMORY`。正常的随机提示冲突
`STATUS_CONFLICTING_ADDRESSES` 不算最终失败；同类申请随后成功会清除对应记录。
只有同一进程带着该记录，以 breakpoint/no-memory/fast-fail 结束时，才停止本次 App 启动代次
里同路径 64 位浏览器的重复启动。崩溃报告进程、32 位程序和其他路径不受此限制。
正常或其他原因的退出会清除旧记录，防止 PEB 地址复用误判。

原生回调只传当前随机启动 ID。Swift 拒绝已结束、旧代次或非 Steam/桌面会话的通知，
显示中文原因、关闭会话和分享日志入口。Steam 更新窗口首帧已经让加载层淡出时，
也能重新显示错误层；错误和旧帧不会伪装为成功。该错误层不提供无效的空回调重试按钮。

这不会强行释放仍可能被其他线程使用的进程内存；停止重复创建避免失败副本继续累积。
当前会话的既有资源仍按正常会话退出流程处理。

## 验证

- 生产放置代码在 ASan/UBSan 下，按用户日志模型对照旧放置与新放置；验证两个完整范围互不重叠，
  16 GB 对齐、64 KiB 保护区和 FEX 边界保留。
- 使用真实 Valve DLL，映射 PE 各节后验证运行时指纹；改变代码/头部、未知进程/代次、后端失败等不得启用。
- 主机 Mach 固定地址核对使用不覆盖映射的调用；本机无法取得这些精确高地址，结果为 **SKIP**，
  不能据此声称已在主机或 iPad 上实分配成功。
- 生产失败处理、并发通知、退出记录清理、成功回退、正常/其他程序隔离和 Swift 回调经过主机执行测试；
  加载层、安装路由和 iOS SDK 类型检查另外验证。

尚未构建新 IPA。真实设备上的 chrome_elf/libcef 初始化、V8、登录界面、点击与渲染均保持 **UNRUN**。
