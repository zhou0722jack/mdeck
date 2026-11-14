# Windows 运行库分组件缓存

GitHub Actions 继续使用 `runtime (windows)` 作为最终组装任务，但编译和二进制缓存
按七个来源分别管理，不再因修改 FEX 就从 Wine 开始重新编译整组。

| 单元 | 输出 | 影响缓存的主要输入 |
| --- | --- | --- |
| wine | ARM64EC/AArch64 Wine DLL，以及 winevulkan | Wine pin、Wine PE 配方、补丁、输出清单 |
| fex32 | aarch64-windows/xtajit.dll | FEX pin、WoW64 配方、共享 FEX 补丁 |
| fex64 | arm64ec-windows/xtajit64.dll | FEX pin、ARM64EC 配方、共享 FEX 补丁 |
| dxmt | DXMT 的 D3D9/10/11、DXGI、winemetal、NVAPI DLL | DXMT pin/补丁、配方、Wine 依赖键 |
| d3d12 | madeira_d3d12.dll、d3d12.dll、d3d12core.dll | D3D12 源码/着色器、DXMT 依赖键 |
| helpers | faultrep.dll、wineios.drv、tftrace-x64.dll | 各辅助模块源码与配方 |
| luajit | lua51.dll、固定版本记录和许可 | 固定 LuaJIT 提交和构建配方 |

每个键还包含当前 SDK/编译环境、MinGW 配方、缓存执行器，以及该单元的元数据。
独立 JSON 条目参与各自哈希，其他条目的修改不会自动使全部缓存失效。共享 FEX
补丁影响 fex32/fex64；只改其中一个架构的构建脚本只影响该架构。Wine 变化会传递到
DXMT，再传递到 D3D12，因为它们需要匹配的 Wine/DXMT 导入库。

只有界面变化且运行库输入不变时，应直接复用整组 Windows 成品缓存。整组成品未
命中时，各单元独立校验/恢复/重建，再组装新的 Windows 清单。第一次采用此结构时
需要建立七份新缓存；不把旧整组缓存冒充成具有独立来源证明的新缓存。

## 新 runner 上的构建依赖

Wine 缓存包含 DXMT 所需的两套 ntdll/dbghelp/winecrt0 导入库与 host winebuild。
DXMT 缓存包含 D3D12 链接所需的 winemetal 导入库。恢复这些文件时验证来源键、哈希、
路径和可执行位。无需恢复带旧机器绝对路径的 Makefile、CMakeCache 或整个对象目录。
DXMT/D3D12 需要重编时，也在干净源码上重新应用 DXMT 补丁。

workflow 每编完一个单元就立即保存独立缓存，因此后面的 FEX 或 App 失败不会丢掉
前面已经成功的 Wine。未完成或未验证的输出不会被保存为成品。首次构建依序执行，
缓存复用后只运行失效单元；外层组件/IPA 仍由现有 `build_ipa=true` 显式授权控制。

## 组装校验

- DLL 的架构、校验值和所属来源都在恢复前验证；跨来源文件或旧依赖键拒绝复用。
- 版本控制中的测试 EXE 独立保留，不来自编译缓存。
- 最终组装仍检查所有 Wine DLL 导入闭包，不因拆分跳过依赖校验。
- 出现缺失 DLL 时直接报错，修正 Wine 输出清单后重建；不会在快照之后偷偷编译并
  混入无法追踪来源的文件。
- App 包内新增 `windows-runtime-parts.json` 记录七个单元的键、依赖和输出哈希；
  外层 `runtime-build.json` 继续绑定完整源树、SDK、运行文件校验值。

验证通过 GitHub Actions 执行。测试使用生产缓存代码和受控的构建命令，验证选择性
失效、只重编 FEX、跨 runner 导入库恢复、失败后保留、架构/哈希/依赖拒绝和最终
导入闭包。完整云端构建再验证真实脚本与支持文件路径，不能用模拟测试代替构建。
