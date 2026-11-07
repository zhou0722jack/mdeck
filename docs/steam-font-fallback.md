# Steam 字体日志：32 位 DirectWrite 的中文字体回退

用户的字体跟踪中，前缀迁移报告 Noto Sans SC verified，GDI/FreeType 成功解析
NotoSansSC-Regular.otf，并将 Noto Sans SC 加入字体家族。说明字体资源和 GDI 路径可用。

同一会话的 DirectWrite 系统字体枚举只有前缀默认的 13 个 TTF 路径，没有 NotoSansSC-Regular.otf。
回退调用反复查找 Noto Sans CJK SC、SimSun、Microsoft YaHei 等名称。

对照生产消费者和内置前缀：

- dwrite/main.c 的 open_fonts_key 在当前注册表视图读取 Windows NT/CurrentVersion/Fonts。
- 内置 system.reg 的普通视图和 Wow6432Node 字体键是两份独立数据；32 位键并非共享链接，内容与日志的 13 个默认路径一致。
- 原 ChineseFonts.h 仅在普通视图登记 Noto，导致 32 位 DirectWrite 不能通过该列表发现字体；GDI 自己扫描 Fonts 目录仍能发现它。
- dwrite/analyzer.c 的 zh-Hans CJK 回退表使用 Noto Sans CJK SC，而字体文件真实家族名为 Noto Sans SC。旧的替换表没有这一名称映射。
- dwrite/font.c 已支持 HKCU/Wine/Fonts/Replacements，因此修复前缀登记与映射即可，无需为此修改 DirectWrite DLL 或字体文件。

## 修正与保留边界

1. 在普通视图和独立的 32 位字体键都登记同一份已打包的 NotoSansSC-Regular.otf。
2. 添加 Noto Sans CJK SC -> Noto Sans SC 的替换，仅在没有用户自定义映射时写入，不覆盖 Steam 的 Motiva Sans 或已有真实字体。
3. 其他前缀若将字体键设为注册表链接，保留链接对象，不向其中塞普通值；普通目标视图仍按原逻辑登记。
4. 日志分别报告 registered64、registered32。保留原有字体授权、字节校验、备份、自定义链接顺序和未知编码保护。
5. 仍在 wineserver 启动前对当前前缀进行迁移；重复启动不产生额外更改，不要求删除已有前缀。

## 验证

主机直接编译执行生产 ChineseFonts.h，使用实际内置前缀，检查两个注册表视图、默认字体保留、CJK 回退别名、
自定义别名/链接顺序、注册表链接不变、备份不覆盖、重复运行幂等、损坏字体修复和缺少资源时不破坏前缀。
同时使用实际字体校验家族名、哈希和简体中文样本文字的 glyph 覆盖。

这是已确认的中文回退缺口；不会把每个空白字形边界或带 err 标签的绘制诊断都认定为字体失败，空格等也可能产生空边界。
尚未打包，也没有 iPad 上的 DirectWrite/CEF 缺字消失验证；不能据此声称所有私有图标或网页字体问题都已解决。
