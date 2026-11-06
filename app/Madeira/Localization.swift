import Foundation

/// This fork presents Madeira in Simplified Chinese, including generated messages.
/// The original keys and other translations remain available in the string catalog.
enum AppLanguage {
    static let locale = Locale(identifier: "zh-Hans")
    static let bundle = Bundle.main.path(forResource: "zh-Hans", ofType: "lproj")
        .flatMap(Bundle.init(path:)) ?? Bundle.main
}

func L(_ text: String) -> String {
    AppLanguage.bundle.localizedString(forKey: text, value: text, table: "Localizable")
}

/// Localize before substituting names, paths, counts or diagnostic details.
func LF(_ format: String, _ arguments: CVarArg...) -> String {
    String(format: L(format), locale: AppLanguage.locale, arguments: arguments)
}
