# Windows Steam 登录同步到 App 商店

用户在 mdeck 内的交互版 Windows Steam 登录后，App 接收同一客户端保存或恢复的
刷新令牌，向 Valve 验证后将授权存入 iOS 钥匙串。正常同步后，App 商店无需再次扫码。

## 数据流程

1. Wine `crypt32` 补丁仅匹配
   `C:\Program Files\Steam Client\Steam.exe`，大小写不敏感。
   在 `CryptProtectData` 成功保存凭据，或 `CryptUnprotectData` 成功恢复凭据后，
   只在最多 64 KiB 的本次 DPAPI 数据中提取完整 JWT，兼容原始、带前缀或包装的
   UTF-8／UTF-16LE 数据；仅把令牌片段交给私有 unixlib 回调，不传包装或相邻内容。
   每个令牌最多 8192 字符，每个数据块最多 4 个候选，不截断过长令牌。
   其他程序、浏览器、
   旧 Dock 的 Steam、密码等普通 DPAPI 数据不走这一传输。
2. 原生与 WOW64 回调使用同一新增表项；WOW64 内嵌指针按当前客体窗口转换成宿主指针。
   候选在回调返回前复制，不持有调用方指针。不改动 DPAPI 的输出、返回值或 LastError。
3. App 仅保留 Steam 签发、同时具有 `client` 和 `derive` 用途、未过期的刷新令牌候选。
   客户端 `config/loginusers.vdf` 只读，用于按令牌 subject 查找
   `MostRecent=1` 的账户名；该文件和 JWT 自述本身都不是授权凭证。
4. Windows/Wine 会话结束后，暂停 App 下载器并释放它原来的 CM 连接。
   使用短期 `SteamSession` 通过 TLS WebSocket 向 Valve CM 提交候选刷新令牌。
   只有真实 ClientLogonResponse 成功、会话认证完成且服务器返回的账号匹配，
   才调用 App 的正式登录存储接口。先关闭临时连接，再允许下载器重新连接。
   不将尚未验证的候选写入正式登录项，也不请求轮换客户端的刷新令牌。
5. 正式授权和待验证候选都只存设备钥匙串，使用
   `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`。候选最多 4 个，导入成功后删除。
   没有明文交接文件，也不把令牌放进命令行、环境变量、日志或备份。
6. 商店观察既有登录通知，刷新当前账号。Windows/Wine 会话运行期间不另建 CM 登录，
   保持下载暂停；会话结束后加载新账号的游戏库并允许原生下载。
   已经打开的 App 登录页会取消原来的扫码／密码等待，并自动关闭。

令牌用途与接口限制核对来源：
[LoginSession](https://github.com/DoctorMcKay/node-steam-session/blob/842d88b673ec094cb3c9af00d247a21788d4cfac/src/LoginSession.ts#L293)。
SteamClient 刷新令牌要求 `client`、`derive`；客户端刷新令牌的访问令牌刷新接口
需要认证 CM 上下文，不能作为独立 HTTPS 验证入口。
CM 消息由项目既有的 `CMsgClientLogon` 与 `CMsgClientLogonResponse` 实现处理。

## 与 Madeira Dock 的区别

核对的上游提交为 `67780ba92e60dbfac4fe80eaf2ce34b9ea1a1c60`。
Dock 正常路径由 App 钥匙串取得令牌，经保护的一次性交接文件调用 Valve 客户端的
`SetLoginToken`、`LogOn`。开发者缓存路径调用客户端的缓存检查与账号选择方法，
让 Valve 自己读取缓存并验证；缓存秘密不被导出到 App。
两条路径都等待真实客户端在线结果，Dock 不负责原生游戏下载。
此同步桥服务的是 Windows Steam → App 原生下载器，不恢复 Dock 组件下载。

## 失败与账号切换

- 离线、临时服务错误或钥匙串写入失败：保留候选，在前台间隔重试。
- Valve 拒绝、过期或响应账号不匹配：不导入该候选，不伪造已登录状态。
- 验证期间切换 Windows 账号：旧响应不得写入；只接收新选中账号的授权。
- 用户启动新 Windows 会话时，先取消并关闭临时 CM 验证连接，再继续启动。
- App 中退出登录或手动选择其他账号：取消旧导入并禁止后台重新导入。
  用户下次主动启动 Windows Steam／桌面会话后，重新允许同步。
- 主授权钥匙串项用更新操作替换；写入失败时保留原授权。
- 账号变化时结束 App 旧连接和旧下载队列，清理旧缓存；延迟返回的旧游戏库、游玩时间
  不得写入新账号的状态或缓存。
- 可用 `env.MADEIRA_STEAM_SIGNIN_SYNC = 0` 关闭此自动同步。

## 使用与验证边界

安装含此改动的新包后，先打开一次 Windows Steam。已有的自动登录若通过客户端的
DPAPI 恢复凭据，同样会触发候选接收，不要求再次输入密码。收到候选后显示“已收到授权”，
结束 Windows 会话后验证并进入 App 游戏商店下载。
安装旧包时完成的登录不能在未运行新桥接代码的情况下追溯同步。

商店会显示等待保存、同步中、重试或失败提示。日志搜索 `[steam-signin-sync]`，
记录只含阶段结果，不含账号、SteamID、令牌或认证请求／响应。
补丁同时抑制指定 Steam 进程的 DPAPI 数据转储，避免开启 crypt 追踪后打印凭据。

Build 23 的诊断缺口：候选筛选前没有日志，而 `renew` 筛选会丢弃正常客户端令牌；
即使通过筛选，独立 HTTPS 验证客户端令牌的方式也不正确。修正版启动时记录
`bridge ready`，Windows 启动时记录 `waiting for Windows credential event`；
候选被拒绝、接收、等待会话结束以及进入 CM 验证都记录固定阶段，保持凭据不入日志。
“没有这个条目”本身不能证明 Windows 没有调用 DPAPI，仍需修正版日志定位入口。

Build 24 真机日志只到 `waiting for Windows credential event`，没有接收或拒绝候选，
也没有进入 CM 验证。它证明 Windows 到 App 的交接尚未到达，不能据此判定网络验证失败。
该版只检查数据开头的 JWT 特征，会漏掉带前缀或包装的数据；这是已修正的代码缺口，
尚不能仅凭旧日志证明它就是该次真机故障的原因。

修正版在 `crypt32` 完成 unixlib 初始化后报告 DLL 接入与进程分类，再分别报告
`CryptProtectData`／`CryptUnprotectData` 入口、成功结果、未提取到完整 JWT 或数据超界。
固定事件通过原有 ABI 的 NULL 指针与 1–12 阶段码传递；未知阶段码丢弃，正常候选仍走
非 NULL 指针与长度检查。Windows 端每个 DLL 实例、App 端每次 Windows 会话分别去重。
这些记录不包含实际路径、数据长度、账号或令牌；事件本身不改变登录状态。
由此可区分未接入 DLL、进程路径不匹配、未调用 DPAPI、DPAPI 未成功和候选格式不符合预期。

`tests/host/check-steam-signin-sync.py` 使用符合客户端用途的合成令牌、假 CM 结果和内存钥匙串，
执行生产同步状态机、账号绑定、失败重试、退出、切换账号及旧游戏库响应隔离逻辑。
它还验证私有 ABI、WOW64 转换、DPAPI 调用范围、LastError 保留和补丁源漂移失败，
并在 ASan／UBSan 下验证原始及包装的 UTF-8／UTF-16、奇数字节偏移、完整片段、
超界和错误语法拒绝、多候选数量限制，以及固定诊断事件不授予登录状态。
并以 iOS SDK 检查完整同步代码、真实 CM 连接代码及登录界面。
交叉编译器可用时，检查三种 PE 架构的完整修改源。

这些结果不代表真实 Steam 登录已经在 iPad 验收。仍需验证当前客户端实际触发凭据回调、
当前 Valve 服务接受令牌复用，以及真实账户游戏库刷新和下载。构建成功不代替这些真机验收。
