# Steam 专用性能检测

入口：Steam 设置 → 高级 → 诊断 → **Steam 专用性能检测**。默认关闭，下次启动
Steam 生效，运行过程中不能修改。全局 Steam 配置在 32 位和 64 位启动时复用。

配置键为 `env.MADEIRA_STEAM_SURFACE_STATS = 1`，`0` 或未设置时关闭。游戏配置
覆盖全局配置。它与原有的“性能日志”（CPU、线程、内存、DXMT 帧统计）、扩展日志、
实时日志分别控制。需要同时分析 CPU 与显示路径时，把两个性能开关都打开。

## 日志

导出同一次运行的日志，搜索 `[steam-surface]`。启动会打印 enabled，随后由独立的
utility 队列约每秒汇总，即使静止没有更新或 UIKit 主线程忙，也会记录主窗口和光标
的心跳。加载动画结束、首次窗口 census 停止后继续记录；Wine 会话结束或重置时取消
定时器并使旧采样失效。定时器不是精确时钟，速率使用实际 `dt` 计算。

`kind` 分类：

| 值 | 含义 |
| --- | --- |
| `steam-main` | 当前最大的可见 Steam 所属窗口；`main_hwnd/main_pid/size` 标识该窗口 |
| `steam-other` | 其他 Steam 窗口，包括弹窗和隐藏窗口 |
| `other` | 已识别所属进程的其他窗口，如 Explorer |
| `unknown` | 尚未获得窗口所属程序，或查询失败 |
| `cursor` | 光标移动与形状更新，不计入 Steam 窗口更新率 |

通过窗口所属进程映像的文件名 `steam.exe` / `steamwebhelper.exe` 识别 Steam，不按
窗口尺寸或名字猜测所属程序。不输出进程完整路径、窗口标题、图像内容或账号信息。
窗口分类使用本次汇总时的元数据，因此登录窗口切换主界面时应结合 `main_hwnd` 阅读。

| 字段 | 含义 |
| --- | --- |
| `session`, `t+`, `dt` | 本次采样代号、启动采样后的秒数、本区间实际秒数 |
| `recv`, `queued`, `applied` | 收到更新、加入主线程队列、成功赋给图层的次数 |
| `skipped`, `failed` | 跳过的更新、复制分配或图像创建失败的次数 |
| `updates/s` | `applied / dt`，是宿主图层更新率，不是显示帧率 |
| `copyMiB/s`, `dirtyMP/s` | 实际快照复制量、裁剪到有效表面的脏区域面积；重复区域重复计数 |
| `pending`, `pendingMiB` | 仍在排队或处理中的更新数、这些更新持有的快照字节数 |
| `peak_pending_sum`, `peakMiB_sum` | 本区间各窗口峰值之和，是分类峰值上界，不是同时发生的精确峰值 |
| `overflow` | 区间内窗口表满而未能记录的事件数；非零表示统计不完整 |

所有 `*_ms` 均为 **平均毫秒 / 最大毫秒 / 本区间完成该阶段的样本数**：

- `copy_ms`：分配并复制快照、交给 NSData 持有的时间。
- `prepare_ms`：复制完成到入队之间的时间，包含原有的表面诊断和日志处理。
- `queue_ms`：入队到主线程开始处理之间的等待时间。
- `image_ms`：创建颜色空间、数据提供者及 CGImage 的调用耗时。延迟解码或后续
  Core Animation 工作不在这个数字中。
- `layer_ms`：设置图层内容及几何等宿主工作；不代表 Core Animation 提交完成、
  GPU 耗时或屏幕已显示。光标路径可能包含原本已有的 CATransaction 调用。
- `main_ms`：主线程处理块总耗时，包含合成器/图层准备以及图像和内容设置。
- `total_ms`：从开始复制/光标更新到宿主处理完成的总时间。

阶段可以跨越两个汇总区间；接收数和完成数不要求相等。未执行的阶段不生成虚假零值
样本。队列跨区间仍保留 pending，窗口销毁后其未完成采样不会算到复用同一 HWND 的
新窗口。固定最多 64 个窗口槽，日志最多每秒 5 类，不逐次打印新增日志、不检查像素、
不暂停线程、不添加 GPU completion handler。已有的表面日志行为保持原样。

## 复测

保持相同分辨率、网络和 Steam 参数，在同一页面依次静止 20 秒、滚动 20 秒、切页
20 秒、再次静止 20 秒，然后在同次会话导出日志。

- `queue_ms` 和 pending 持续升高：主线程无法及时处理到达的图像。
- `copy_ms` / 复制量高：优先调查图像复制成本。
- `prepare_ms` 高：检查已有诊断、转储或日志本身的开销。
- `image_ms` / `layer_ms` / `main_ms` 高：调查宿主图像与图层处理。
- 上述耗时低，但 CEF 线程 CPU 时间高且更新少：继续调查 CEF 执行与软件渲染。

这里的更新可能是局部脏区域、重复图像或隐藏窗口更新，不能由它计算真实显示 FPS，
也不能据此认定 GPU 饱和。实际屏幕呈现和 GPU 性能仍需系统侧工具或单独的呈现采样。

## 分配与重试计时

同一个“Steam 专用性能检测”开关现在同时启用 `[steam-alloc]`，无需额外设置。
沿用窗口统计的后台 utility 定时器，每秒输出一个总量、最多 8 条线程与申请大小分组，
以及未逐项输出的 remainder 汇总；每次 API 调用本身不新增日志。

普通 `NtAllocateVirtualMemory` 和扩展 `NtAllocateVirtualMemoryEx` 都覆盖，包括参数
拒绝、远程请求和未经过普通分配器的特殊路径。嵌套 API 不重复计入整次请求；内部
`allocate_virtual_memory` 的递归嵌套耗时只计入其最外层尝试。

| 字段 | 含义 |
| --- | --- |
| `requests/success/failed` | 本区间完成的 API 请求数、最终成功数、最终失败数 |
| `final_conflict` | API 最终以地址冲突状态返回的次数，不代表物理内存耗尽 |
| `hinted/remote` | 带初始指定地址的请求数、目标为其他进程的请求数；pid/tid 是发起者 |
| `attempts/attempt_failed` | 内部普通分配器尝试数及其中返回失败的次数 |
| `conflicts/hinted_conflicts` | 内部尝试返回地址冲突次数，其中带指定地址的次数 |
| `recovered` | 内部曾发生地址冲突，但 API 最终成功的请求数 |
| `retry_requests/retries` | 一次 API 内进行了多次普通分配器尝试的请求数、首次以后尝试总数 |
| `low_try/low_success/low_miss` | guest 低 2 GB 预尝试次数、成功数、失败数 |
| `fallback_success/fallback_failed` | 至少一次低地址预尝试失败后，整个 API 最终成功/失败的请求数 |
| `size/min_bytes/max_bytes/requestedMiB` | 申请大小分组、原始请求大小最小/最大值、累计申请量；不是实际占用量 |
| `pid/tid/api/types` | 发起进程、线程、API、分组中的请求 type 标志按位合并 |

所有 `*_ms` 仍为 **平均毫秒 / 最大毫秒 / 样本数**：

- `total_ms`：一次 API 的总耗时，含原有诊断与锁等待；特殊分配路径也有记录。
- `attempt_ms`：一次最外层内部普通分配器调用耗时，含其锁等待。
- `conflict_ms` / `hinted_conflict_ms`：返回地址冲突的内部尝试耗时、其中指定地址尝试耗时。
- `retry_ms`：一次 API 内首次内部尝试之后的尝试耗时。
- `low_ms`：仅 guest 低 2 GB 的 `map_reserved_area` 搜索调用耗时。
- `fallback_ms`：低地址搜索失败后，至该次 `map_view` 返回的耗时，含原有回退日志和后续路径。
- `wall_ms_sum`：完成请求的累计总墙钟毫秒；多线程可能重叠，不等于 CPU 时间，也不能将
  total、attempt、low、fallback 等包含关系的时间相加。

大小按 `<64 KiB`、`64 KiB～<1 MiB`、`1～<4 MiB`、`4～<16 MiB`、`16～<128 MiB`、
`128 MiB～<1 GiB`、`≥1 GiB` 分组。每区间最多 128 个线程/大小/API 归因槽，满后
`overflow` 计数增加，但总量和 remainder 继续累计，不丢失已完成请求的总统计。Top 8
按累计请求墙钟时间选取。统计窗口跨秒的请求在完成时一次性归属，不拆分成多次请求。

调用者收到冲突后再次调用 API，属于另一个请求；本功能不猜测两个 API 是否来自同一个
guest 重试循环。内部普通分配器之外的特殊快速路径、软预留等不伪造 `attempts`。
低地址分配是 guest 地址布局，与宿主 JIT C 区分开。计时不改变地址、参数、回退策略或
返回状态，关闭开关时不启动计时器、计时及聚合操作。

## 验证边界

GitHub Actions 的检查执行生产计数器、计时/会话适配器以及 iPhoneOS 语法检查。
这不等于在 iPad 上验证 Steam，也不产生 IPA。设备日志验收需要后续明确要求构建后
安装新版本，确认 `[steam-surface]` 持续输出并复现上述操作。
