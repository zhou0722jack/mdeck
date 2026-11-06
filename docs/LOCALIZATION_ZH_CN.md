# 简体中文界面

此 fork 默认使用简体中文显示 Madeira 的游戏库和开发者界面。游戏名、
文件路径、商店标识、配置键、按键映射及游戏本身的语言设置保持原样。

界面文案集中在 app/Madeira/Localizable.xcstrings。SwiftUI 的文字常量
通过页面的中文 locale 显示；程序生成的标题、状态和错误使用
Localization.swift 中的 L 或 LF。格式化消息先翻译模板，再填入
游戏名、文件路径、进度和错误码，避免对这些数据做翻译。

“全部设置”的标题、分类、选项和说明同样使用字符串目录。自动生成的
ConfigCatalog.generated.swift 保留英文源文案与配置值，以便继续从
上游更新；界面展示对应的中文说明，搜索同时支持中文和原始配置键。
上游已有的其他语言翻译保留。

## 验证

在具有 Xcode 的 Mac 上运行：

    python3 tests/host/check-localization.py
    python3 tests/host/check-control-presets.py
    python3 tests/host/check-steam-cm-transport.py

本地化检查验证全部中文条目、格式参数类型、动态文案和高级设置覆盖，
并用 Xcode 编译实际字符串目录，再在英文系统偏好的测试应用中验证中文
读取、路径和百分比格式。Build IPA 工作流会先运行本地化检查，
通过后继续完整的原生依赖和 IPA 构建。

在 GitHub 的 Actions 页面选择 **Build IPA** 可以手动构建。
向 main 推送也会触发构建。成功运行的产物位于 **Madeira-ipa** 中，
包含 Madeira.ipa；安装时需要使用自己的侧载签名工具重新签名。
