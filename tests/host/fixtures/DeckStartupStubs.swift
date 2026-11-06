import SwiftUI

func L(_ key: String) -> String { key }

@MainActor enum StartupFixture {
    static var calls: [DeckSetupComponent] = []
    static var failures: Set<DeckSetupComponent> = []
    static var sessionRunning = false
    static func download(_ component: DeckSetupComponent, finish: @escaping (Bool) -> Void) {
        calls.append(component)
        Task {
            try? await Task.sleep(nanoseconds: 10_000_000)
            finish(!failures.contains(component))
        }
    }
    static func reset() {
        calls = []; failures = []; sessionRunning = false
        WineMonoModel.available = false; WineMonoModel.shared.error = nil
        VCRedistModel.shared.complete = false; VCRedistModel.shared.error = nil
        WineGeckoModel.available = false; WineGeckoModel.shared.error = nil
        MadeiraDock.bundled = true; MadeiraDock.clientInstalled = false; MadeiraDockModel.shared.error = nil
        MadeiraBuiltInJIT.isAvailable = true
    }
}

@MainActor func wine_process_is_running() -> Int32 { StartupFixture.sessionRunning ? 1 : 0 }
@MainActor func wineserver_is_running() -> Int32 { StartupFixture.sessionRunning ? 1 : 0 }

@MainActor final class LibraryModel: ObservableObject {
    static let shared = LibraryModel()
    @Published var current: UUID?
}
@MainActor final class LogStore {
    static let shared = LogStore()
    func log(_ text: String) {}
}
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
@MainActor final class MadeiraDockModel {
    static let shared = MadeiraDockModel()
    var preparing = false
    var error: String?
    var progress = "Downloading Steam components (1 of 3)…"
    func prepareClient() {
        guard !preparing else { return }
        error = nil; preparing = true
        StartupFixture.download(.dock) { ok in
            MadeiraDock.clientInstalled = ok; self.error = ok ? nil : "dock offline"; self.preparing = false
        }
    }
}
@MainActor enum MadeiraBuiltInJIT {
    static var isAvailable = true
    static var unavailableReason: String? { isAvailable ? nil : "Unavailable inside LiveContainer" }
}
@MainActor final class JITCoordinator {
    static let shared = JITCoordinator()
    var method: JITMethod = .externalScript
}
enum StikJITHelper { static var scriptURL: URL? { nil } }
struct JITSetupView: View { var body: some View { EmptyView() } }
enum SettingsPages {
    enum Page: String, CaseIterable {
        case steam, library, graphics
        var title: String { rawValue }
        var symbol: String { "gearshape" }
        var shown: Bool { true }
    }
}
