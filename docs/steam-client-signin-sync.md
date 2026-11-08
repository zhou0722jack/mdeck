# Windows Steam 登录同步到 App 商店

用户在 mdeck 内的交互版 Windows Steam 登录后，App 接收同一客户端保存或恢复的
刷新令牌，向 Valve 验证后将授权存入 iOS 钥匙串。正常同步后，App 商店无需再次扫码。

## 数据流程

1. Wine `crypt32` 补丁仅匹配
   `C:\Program Files\Steam Client\Steam.exe`，大小写不敏感。
   在 `CryptProtectData` 成功保存凭据，或 `CryptUnprotectData` 成功恢复凭据后，
   只将有 JWT 字节特征的有界候选数据交给私有 unixlib 回调。其他程序、浏览器、
   旧 Dock 的 Steam、密码等普通 DPAPI 数据不走这一传输。
2. 原生与 WOW64 回调使用同一新增表项；WOW64 内嵌指针按当前客体窗口转换成宿主指针。
   候选在回调返回前复制，不持有调用方指针。不改动 DPAPI 的输出、返回值或 LastError。
3. App 仅保留 Steam 签发、具有 `renew` 用途、未过期的刷新令牌候选。
   客户端 `config/loginusers.vdf` 只读，用于按令牌 subject 查找
   `MostRecent=1` 的账户名；该文件和 JWT 自述本身都不是授权凭证。
4. 经 HTTPS 向 Valve 的 `IAuthenticationService/GenerateAccessTokenForApp/v1/`
   发送候选，使用公开协议的 `refresh_token=1`、`fixed64 steamid=2`，不请求轮换令牌。
   Valve 接受且响应访问令牌的账号匹配后，才调用 App 的正式登录存储接口。
5. 正式授权和待验证候选都只存设备钥匙串，使用
   `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`。候选最多 4 个，导入成功后删除。
   没有明文交接文件，也不把令牌放进命令行、环境变量、日志或备份。
6. 商店观察既有登录通知，刷新当前账号。Windows/Wine 会话运行期间不另建 CM 登录，
   保持下载暂停；会话结束后加载新账号的游戏库并允许原生下载。
   已经打开的 App 登录页会取消原来的扫码／密码等待，并自动关闭。

公开协议字段核对来源：
[Steam Authentication protobuf definitions](https://github.com/SteamDatabase/Protobufs/blob/master/steam/steammessages_auth.steamclient.proto)，
`CAuthentication_AccessToken_GenerateForApp_Request/Response`。

## 失败与账号切换

- 离线、临时服务错误或钥匙串写入失败：保留候选，在前台间隔重试。
- Valve 拒绝、过期或响应账号不匹配：不导入该候选，不伪造已登录状态。
- 验证期间切换 Windows 账号：旧响应不得写入；只接收新选中账号的授权。
- App 中退出登录或手动选择其他账号：取消旧导入并禁止后台重新导入。
  用户下次主动启动 Windows Steam／桌面会话后，重新允许同步。
- 主授权钥匙串项用更新操作替换；写入失败时保留原授权。
- 账号变化时结束 App 旧连接和旧下载队列，清理旧缓存；延迟返回的旧游戏库、游玩时间
  不得写入新账号的状态或缓存。
- 可用 `env.MADEIRA_STEAM_SIGNIN_SYNC = 0` 关闭此自动同步。

## 使用与验证边界

安装含此改动的新包后，先打开一次 Windows Steam。已有的自动登录若通过客户端的
DPAPI 恢复凭据，同样会触发同步，不要求再次输入密码。同步完成后结束 Windows 会话，
再进入 App 游戏商店下载。安装旧包时完成的登录不能在未运行新桥接代码的情况下追溯同步。

商店会显示等待保存、同步中、重试或失败提示。日志搜索 `[steam-signin-sync]`，
记录只含阶段结果，不含账号、SteamID、令牌或认证请求／响应。
补丁同时抑制指定 Steam 进程的 DPAPI 数据转储，避免开启 crypt 追踪后打印凭据。

`tests/host/check-steam-signin-sync.py` 使用合成令牌、假 Valve 响应和内存钥匙串，
执行生产同步状态机、账号绑定、失败重试、退出、切换账号及旧游戏库响应隔离逻辑。
它还验证私有 ABI、WOW64 转换、DPAPI 调用范围、LastError 保留和补丁源漂移失败，
并以 iOS SDK 检查完整同步代码。交叉编译器可用时，检查三种 PE 架构的完整修改源。

这些结果不代表真实 Steam 登录已经在 iPad 验收。仍需验证当前客户端实际触发凭据回调、
当前 Valve 服务接受令牌复用，以及真实账户游戏库刷新和下载。本轮不构建 IPA。
