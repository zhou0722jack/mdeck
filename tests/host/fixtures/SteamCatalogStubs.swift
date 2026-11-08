import SwiftUI
import Combine
func L(_ value: String) -> String { value }
func LF(_ value: String, _ arguments: CVarArg...) -> String { String(format: value, arguments: arguments) }
struct DockGame: Equatable { var id: Int; var installed: Bool; var name = "Local fixture" }
struct SteamOwnedGame: Equatable {
    var id: Int; var name: String
    var installBytes: UInt64? = nil
    var libraryCapsule: String? = nil, libraryHero: String? = nil, headerImage: String? = nil
    var parentID: Int? = nil
}
struct LibraryEntry: Identifiable {
    var id = UUID(); var title = "Fixture"; var steamAppID: Int?
    var lastPlayed: Date?; var folderBytes: Int64?
}
final class LibraryModel: ObservableObject {
    static let shared = LibraryModel()
    @Published var entries: [LibraryEntry] = []
    @Published var launching = false
    func steamEntry(_ game: DockGame, title: String) -> LibraryEntry { LibraryEntry(title: title, steamAppID: game.id) }
}
final class SteamGamesModel: ObservableObject {
    static let shared = SteamGamesModel()
    @Published var games: [DockGame] = []
    var builds: [Int: Int] = [:], branches: [Int: String] = [:]
    func refresh() {}
}
struct FixtureProgress { var fraction = 0.0 }
struct SteamPlaytime { var summary: String?; var lastPlayed = 0 }
final class SteamOwnedLibrary: ObservableObject {
    static let shared = SteamOwnedLibrary()
    struct Download {
        enum State { case queued, active, paused, failed(String) }
        var state: State; var progress = FixtureProgress()
        var transfer: SteamGamesRules.Transfer {
            switch state {
            case .queued: return .queued
            case .active: return .active(percent: Int(progress.fraction * 100))
            case .paused: return .paused
            case .failed: return .failed
            }
        }
    }
    @Published var signedIn = false
    @Published var inSession = false
    @Published var owned: [SteamOwnedGame] = []
    @Published var downloads: [Int: Download] = [:]
    @Published var refreshing = false
    @Published var error: String?
    var cloudWaitingFor: Int?
    @Published var playtime: [Int: SteamPlaytime] = [:]
    func start() {}
    func reconcileSession() {}
    func refreshAfterForeground() {}
    func refreshLibrary(interactive: Bool) async {}
    func updateAvailable(appID: Int, installedBuild: Int?, installedBranch: String?) -> Bool { false }
    func install(_ id: Int) {}
    func pause(_ id: Int) {}
}
final class LibraryController: ObservableObject {
    static let shared = LibraryController(); let commands = PassthroughSubject<String, Never>()
}
final class DeckAppearance: ObservableObject { static let shared = DeckAppearance(); @Published var animations = true }
final class DeckSteamLaunchPreparation { static let shared = DeckSteamLaunchPreparation(); var presented = false }
struct Palette {
    var background = Color.black, text = Color.white, muted = Color.gray, accent = Color.green
    var surface = Color.gray.opacity(0.1), line = Color.gray.opacity(0.3)
}
struct PaletteKey: EnvironmentKey { static let defaultValue = Palette() }
extension EnvironmentValues { var deckPalette: Palette { get { self[PaletteKey.self] } set { self[PaletteKey.self] = newValue } } }
struct DeckButtonStyle: ButtonStyle { var primary = false; func makeBody(configuration: Configuration) -> some View { configuration.label } }
struct DeckHomeRise: ViewModifier { let index: Int; let enabled: Bool; func body(content: Content) -> some View { content } }
struct SteamGameArtwork: View { let appID: Int; var backdrop = false; var body: some View { Color.gray } }
struct SteamDownloadStatus: View { let download: SteamOwnedLibrary.Download; var body: some View { Color.clear } }
struct LibraryDetail: View { let entry: LibraryEntry; let play: (LibraryEntry) -> Void; var body: some View { Color.clear } }
struct SteamSignInView: View { var body: some View { Color.clear } }
final class SteamClientSignInSync: ObservableObject {
    static let shared = SteamClientSignInSync()
    enum Phase { case idle, failed }
    var phase = Phase.idle
    var statusText: String? { nil }
}
struct SteamAccountSettingsView: View { var body: some View { Color.clear } }
struct SteamGameSheet: View { let appID: Int; let open: (LibraryEntry) -> Void; var body: some View { Color.clear } }
struct SteamGamePreviewContent: View { let appID: Int; var body: some View { Color.clear } }
