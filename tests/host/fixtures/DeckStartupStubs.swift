import SwiftUI

func L(_ key: String) -> String { key }
func LF(_ key: String, _ arguments: CVarArg...) -> String { String(format: key, arguments: arguments) }
@MainActor func isDebuggerAttached() -> Bool { true }

@MainActor enum StartupFixture {
    static var calls: [DeckSetupComponent] = []
    static var failures: Set<DeckSetupComponent> = []
    static var sessionRunning = false
    static var active: Set<DeckSetupComponent> = []
    static var peakDownloads = 0
    static func download(_ component: DeckSetupComponent, finish: @escaping (Bool) -> Void) {
        calls.append(component)
        active.insert(component)
        peakDownloads = max(peakDownloads, active.count)
        Task {
            try? await Task.sleep(nanoseconds: 10_000_000)
            active.remove(component)
            finish(!failures.contains(component))
        }
    }
    static func reset() {
        calls = []; failures = []; sessionRunning = false; active = []; peakDownloads = 0
        WineMonoModel.available = false; WineMonoModel.shared.error = nil
        VCRedistModel.shared.complete = false; VCRedistModel.shared.error = nil
        WineGeckoModel.available = false; WineGeckoModel.shared.error = nil
        MadeiraDock.bundled = true; MadeiraDock.clientInstalled = false
        MadeiraBuiltInJIT.isAvailable = true
    }
}

@MainActor func wine_process_is_running() -> Int32 { StartupFixture.sessionRunning ? 1 : 0 }
@MainActor func wineserver_is_running() -> Int32 { StartupFixture.sessionRunning ? 1 : 0 }

struct DeckLocalCoverEntry { var coverFile: String? }
@MainActor final class LibraryModel: ObservableObject {
    static let shared = LibraryModel()
    @Published var current: UUID?
    var entries: [DeckLocalCoverEntry] = []
    static var documents: URL { URL(fileURLWithPath: "/tmp") }
    var error: String?
    var restartNotice: String?
    var jitNotice: String?
    func requestQuit() {}
}
@MainActor final class LogStore {
    static let shared = LogStore()
    func log(_ text: String) {}
    var logURL: URL { URL(fileURLWithPath: "/tmp/mdeck-test-log.txt") }
}
enum TouchControlsHost { @MainActor static func attach() {} }
enum SteamClient {
    static let windowsExecutable = "C:\\Program Files\\Steam Client\\Steam.exe"
    static let settingsWindowsExecutable = windowsExecutable
}
enum DeckSteamLocalCovers { @MainActor static func images() -> [Image] { [] } }
@MainActor final class WineMonoModel {
    static let shared = WineMonoModel()
    static var available = false
    enum Phase: Equatable { case idle, downloading(Double), installing(Double) }
    var phase: Phase = .idle
    var error: String?
    var busy: Bool { phase != .idle }
    func install() {
        guard !busy else { return }
        error = nil; phase = .downloading(0)
        StartupFixture.download(.mono) { ok in
            Self.available = ok; self.error = ok ? nil : "mono offline"; self.phase = .idle
        }
    }
}
@MainActor final class VCRedistModel {
    static let shared = VCRedistModel()
    enum Phase: Equatable { case idle, downloading(Double), installing(Double) }
    var phase: Phase = .idle
    var complete = false
    var error: String?
    var busy: Bool { phase != .idle }
    func refresh() {}
    func install() {
        guard !busy else { return }
        error = nil; phase = .downloading(0)
        StartupFixture.download(.visualCPP) { ok in
            self.complete = ok; self.error = ok ? nil : "C++ offline"; self.phase = .idle
        }
    }
}
@MainActor final class WineGeckoModel {
    static let shared = WineGeckoModel()
    static var available = false
    var progress: Double?
    var error: String?
    var busy: Bool { progress != nil }
    func install() {
        guard !busy else { return }
        error = nil; progress = 0
        StartupFixture.download(.gecko) { ok in
            Self.available = ok; self.error = ok ? nil : "gecko offline"; self.progress = nil
        }
    }
}
@MainActor enum MadeiraDock {
    static var bundled = true
    static var clientInstalled = false
}
@MainActor enum MadeiraBuiltInJIT {
    static var isAvailable = true
    static var unavailableReason: String? { isAvailable ? nil : "Unavailable inside LiveContainer" }
}
@MainActor final class JITCoordinator {
    static let shared = JITCoordinator()
    var method: JITMethod = .externalScript
    func enable(completion: @escaping (Result<Void, Error>) -> Void) { completion(.success(())) }
}
enum StikJITHelper {
    static var scriptURL: URL? { nil }; static var ready: Bool { true }
    static var poolTaken: Bool { true }
    static var poolFailure: String? { nil }
    static func requestedPoolMB(in values: [String: String]) -> Int { 896 }
    static func allocatePool(poolSize: Int, configuration: [String: String]) -> Int? { 1 }
    static func bindEntryProbe() -> Int64 { 0 }
}
enum MadeiraConfig { static func all() -> [String: String] { [:] } }
struct GameProfile { let windowsPath: String; var values: [String: String] { [:] } }
struct EntitlementStatus {
    var increasedMemory = true
    static func check() -> Self { Self() }
}
struct JITSetupView: View { var body: some View { EmptyView() } }
enum SettingsPages {
    enum Page: String, CaseIterable {
        case steam, library, graphics
        var title: String { rawValue }
        var symbol: String { "gearshape" }
        var shown: Bool { true }
    }
}
