import Foundation
import Combine
import CryptoKit

@MainActor final class UIApplication {
    static let shared = UIApplication()
    enum State { case active, inactive }
    var applicationState = State.active
    static let didBecomeActiveNotification = Notification.Name("FixtureActive")
}
@MainActor final class LibraryModel {
    static let shared = LibraryModel()
    static var drive = URL(fileURLWithPath: "/tmp")
    var current: Int?
}
func wine_process_is_running() -> Int32 { 0 }
func wineserver_is_running() -> Int32 { 0 }
enum SteamClient { static var clientDirectory = "Program Files/Steam Client" }
@MainActor enum SteamLog {
    static var events: [String] = []
    static func event(_ value: String) { events.append(value) }
}
@MainActor enum SteamSignIn {
    static let didChange = Notification.Name("FixtureSignInChanged")
    static let didSignOut = Notification.Name("FixtureSignOut")
    static var saved: (accountName: String, refreshToken: String, access: String)?
    static var canStore = true, enabled = true, stores = 0
    static var isSignedIn: Bool { saved != nil }
    static var accountName: String? { saved?.accountName }
    static func flag(_ name: String, default value: Bool) -> Bool { enabled }
    static func credentialsForDock() -> (accountName: String, refreshToken: String)? { saved.map { ($0.accountName, $0.refreshToken) } }
    static func store(accountName: String, refreshToken: String, accessToken: String) -> Bool {
        guard canStore else { return false }
        stores += 1; saved = (accountName, refreshToken, accessToken)
        DispatchQueue.main.async { NotificationCenter.default.post(name: didChange, object: nil) }
        return true
    }
    static func signOut() {
        NotificationCenter.default.post(name: didSignOut, object: nil)
        saved = nil
    }
}
@MainActor enum SteamClientPendingStore {
    static var values: [SteamClientSignInRules.Candidate] = []
    static var writable = true
    static func load() -> [SteamClientSignInRules.Candidate] { values }
    @discardableResult static func save(_ values: [SteamClientSignInRules.Candidate]) -> Bool {
        guard writable else { return false }; Self.values = values; return true
    }
}
func token(subject: UInt64 = 0x0110000100000001, audiences: [String] = ["client", "derive"], expires: Date = Date().addingTimeInterval(86400), label: String = "fixture", header: String = #"{"alg":"RS256","typ":"JWT"}"#) -> String {
    func encode(_ data: Data) -> String { data.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "") }
    let body = try! JSONSerialization.data(withJSONObject: ["iss":"steam", "sub":String(subject), "aud":audiences, "exp":expires.timeIntervalSince1970, "jti":label], options: .sortedKeys)
    return encode(Data(header.utf8)) + "." + encode(body) + ".synthetic_signature"
}
@MainActor enum CMVerifierFixture {
    enum Mode { case success, denied, offline, hold, wrongAccount }
    static var mode = Mode.success, calls = 0
    static var waiting: CheckedContinuation<UInt64, Error>?
    static func login(_ credentials: (accountName: String, refreshToken: String)) async throws -> UInt64 {
        precondition(LibraryModel.shared.current == nil, "CM validation must wait for Windows to end")
        precondition(SteamOwnedLibrary.shared.leases == 1, "validator must hold the account before CM login")
        calls += 1
        let subject = UInt64(SteamClientSignInRules.claims(credentials.refreshToken)!["sub"] as! String)!
        switch mode {
        case .denied: throw SteamError.logonDenied(5)
        case .offline: throw URLError(.networkConnectionLost)
        case .hold: return try await withCheckedThrowingContinuation { waiting = $0 }
        case .wrongAccount: return subject + 1
        case .success: return subject
        }
    }
    static func release(subject: UInt64 = 0x0110000100000001) {
        let saved = waiting; waiting = nil; saved?.resume(returning: subject)
    }
    static func cancelWait() {
        let saved = waiting; waiting = nil; saved?.resume(throwing: CancellationError())
    }
}
enum SteamConnectionState { case disconnected, authenticated }
@MainActor final class SteamSession {
    var steamID: UInt64 = 0
    var connectionState = SteamConnectionState.disconnected
    private var suspended = false
    private var ownsWait = false
    init(automaticallyReconnect: Bool = true) { precondition(!automaticallyReconnect) }
    func connectAndLogin(credentialsOverride: (accountName: String, refreshToken: String)? = nil) async throws {
        ownsWait = CMVerifierFixture.mode == .hold
        defer { ownsWait = false }
        let subject = try await CMVerifierFixture.login(credentialsOverride!)
        guard !suspended else { throw SteamError.disconnected }
        steamID = subject; connectionState = .authenticated
    }
    func suspend() async {
        suspended = true; steamID = 0; connectionState = .disconnected
        if ownsWait { ownsWait = false; CMVerifierFixture.cancelWait() }
    }
}
@MainActor final class SteamOwnedLibrary {
    static let shared = SteamOwnedLibrary()
    var leases = 0
    func prepareClientSignInVerification() async { leases += 1 }
    func finishClientSignInVerification(imported: Bool) { leases -= 1; precondition(leases >= 0) }
}

// PRODUCTION_MODEL

// PRODUCTION_LIBRARY_ACCOUNT_TEST

extension SteamClientSignInSync {
    func testTick() { retryAt = .distantPast; tick() }
    func testDispose() {
        _ = closeVerifier()
        revision = UUID(); task?.cancel(); task = nil
        timer?.invalidate(); timer = nil
        for observer in observers { NotificationCenter.default.removeObserver(observer) }; observers = []
    }
}

@main struct Checks {
    @MainActor static func settle() async { for _ in 0..<30 { try? await Task.sleep(nanoseconds: 1_000_000) } }
    @MainActor static func main() async throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1]); LibraryModel.drive = root
        let login = root.appendingPathComponent(SteamClient.clientDirectory + "/config/loginusers.vdf")
        try FileManager.default.createDirectory(at: login.deletingLastPathComponent(), withIntermediateDirectories: true)
        func account(_ subject: UInt64 = 0x0110000100000001, recent: Bool = true) throws {
            try "\"users\" { \"\(subject)\" { \"AccountName\" \"fixture_user\" \"MostRecent\" \"\(recent ? 1 : 0)\" } }"
                .write(to: login, atomically: true, encoding: .utf8)
        }
        let key = "mdeck.steam.client-signin.suppressed", savedPreference = UserDefaults.standard.object(forKey: "mdeck.steam.client-signin.suppressed")
        defer { UserDefaults.standard.set(savedPreference, forKey: key) }
        var sync: SteamClientSignInSync?
        func fresh() -> SteamClientSignInSync {
            sync?.testDispose(); SteamSignIn.saved = nil; SteamSignIn.stores = 0; SteamSignIn.canStore = true; SteamSignIn.enabled = true
            SteamClientPendingStore.values = []; SteamClientPendingStore.writable = true
            CMVerifierFixture.mode = .success; CMVerifierFixture.calls = 0; UIApplication.shared.applicationState = .active
            LibraryModel.shared.current = nil
            SteamClient.clientDirectory = "Program Files/Steam Client"
            let next = SteamClientSignInSync(); sync = next; next.beginSteamSession(); return next
        }
        let refresh = token(header: #"{ "typ": "JWT", "alg": "RS256" }"#), data = Data(refresh.utf8)
        let candidate = SteamClientSignInRules.candidate(data)!
        precondition(SteamClientSignInRules.candidate(Data("password fixture".utf8)) == nil)
        precondition(SteamClientSignInRules.candidate(Data(token(audiences: ["web", "derive"]).utf8)) == nil)
        precondition(SteamClientSignInRules.candidate(Data(token(audiences: ["client"]).utf8)) == nil)
        precondition(SteamClientSignInRules.candidate(Data(token(audiences: ["renew"]).utf8)) == nil)
        precondition(SteamClientSignInRules.candidate(data) != nil, "client + derive token without renew must be accepted")
        precondition(SteamClientSignInRules.candidate(Data(token(expires: .distantPast).utf8)) == nil)
        precondition(SteamClientSignInRules.candidate(Data(repeating: 65, count: 20000)) == nil)
        precondition(SteamClientSignInRules.candidate(Data((refresh + "\0").utf8))?.refresh == refresh)
        precondition(SteamClientSignInRules.candidate((refresh + "\0").data(using: .utf16LittleEndian)!)?.refresh == refresh)
        for header in [#"{"alg":"RS256","typ":"JWT"}"#, #"{ "typ": "JWT", "alg": "RS256" }"#,
                       "  {\"typ\":\"JWT\",\"alg\":\"RS256\"}", "\n{\n\"kid\":\"fixture\", \"alg\":\"RS256\", \"typ\":\"JWT\"\n}"] {
            let value = token(header: header)
            precondition(SteamClientSignInRules.candidate(Data(value.utf8))?.refresh == value)
            precondition(SteamClientSignInRules.candidate(value.data(using: .utf16LittleEndian)!)?.refresh == value)
        }
        for header in ["not a JSON header", "[]", #"{"typ":"JWT"}"#, #"{"alg":"none","typ":"JWT"}"#, #"{"alg":42}"#] {
            precondition(SteamClientSignInRules.candidate(Data(token(header: header).utf8)) == nil)
        }
        precondition(!SteamClientSignInRules.acceptsCMSubject(candidate.subject + 1, candidate: candidate))
        precondition(!SteamClientSignInRules.acceptsCMSubject(0, candidate: candidate))
        print("PASS: only bounded, unexpired refresh JWT candidates survive; UTF-8/UTF-16 and response account binding checked")

        let probes = fresh(), initialEvents = SteamLog.events.count, initialPhase = probes.phase
        precondition(SteamClientAuthProbe.allCases.map(\.rawValue) == Array(1...12))
        for probe in SteamClientAuthProbe.allCases {
            probes.receiveProbe(probe.rawValue); probes.receiveProbe(probe.rawValue)
        }
        probes.receiveProbe(0); probes.receiveProbe(13); probes.receiveProbe(UInt32.max)
        precondition(SteamLog.events.count == initialEvents + 12 && probes.phase == initialPhase)
        precondition(Array(SteamLog.events.suffix(12)) == SteamClientAuthProbe.allCases.map(\.message))
        precondition(CMVerifierFixture.calls == 0 && SteamSignIn.saved == nil && SteamClientPendingStore.values.isEmpty)
        probes.beginSteamSession()
        let newSessionEvents = SteamLog.events.count
        probes.receiveProbe(1); probes.receiveProbe(1)
        precondition(SteamLog.events.count == newSessionEvents + 1)
        print("PASS: fixed Windows diagnostics deduplicate per session, reject unknown codes and never change authorization")

        try account(recent: false)
        var current = fresh(); current.receive(data); await settle()
        precondition(SteamSignIn.saved == nil && CMVerifierFixture.calls == 0 && current.phase == .waitingForAccount)
        try account(); current.testTick(); await settle()
        precondition(current.phase == .synced && SteamSignIn.saved?.refreshToken == refresh && SteamSignIn.stores == 1)
        current.receive(data); await settle(); precondition(SteamSignIn.stores == 1)
        precondition(SteamClientPendingStore.values.isEmpty)
        print("PASS: selected account plus Valve validation imports once and removes the pending transfer")

        current = fresh(); LibraryModel.shared.current = 1; current.receive(data); await settle()
        precondition(current.phase == .waitingForWindows && CMVerifierFixture.calls == 0 && SteamSignIn.saved == nil)
        precondition(current.hasPendingAuthorization && SteamClientPendingStore.values.count == 1)
        LibraryModel.shared.current = nil; current.testTick(); await settle()
        precondition(current.phase == .synced)
        print("PASS: Windows keeps its session; captured authorization validates only after the Windows session ends")

        current = fresh(); CMVerifierFixture.mode = .hold; current.receive(data); await settle()
        var launched = false
        precondition(current.deferWindowsLaunch { launched = true; LibraryModel.shared.current = 1 })
        await settle(); precondition(launched)
        CMVerifierFixture.release(); await settle(); precondition(SteamSignIn.saved == nil)
        LibraryModel.shared.current = nil; CMVerifierFixture.mode = .success; current.testTick(); await settle()
        precondition(current.phase == .synced)
        print("PASS: a new Windows launch closes an in-flight CM validator and stale success cannot import afterward")

        current = fresh(); CMVerifierFixture.mode = .wrongAccount; current.receive(data); await settle()
        precondition(current.phase == .failed && SteamSignIn.saved == nil && SteamClientPendingStore.values.isEmpty)
        current = fresh(); CMVerifierFixture.mode = .denied; current.receive(data); await settle()
        precondition(current.phase == .failed && SteamSignIn.saved == nil)
        current = fresh(); CMVerifierFixture.mode = .offline; current.receive(data); await settle()
        precondition(current.phase == .retrying && SteamSignIn.saved == nil && SteamClientPendingStore.values.count == 1)
        CMVerifierFixture.mode = .success; current.testTick(); await settle(); precondition(current.phase == .synced)
        print("PASS: denied/mismatched tokens never sign in; temporary transport failure retries without losing the candidate")

        current = fresh(); UIApplication.shared.applicationState = .inactive; current.receive(data)
        precondition(SteamClientPendingStore.values.count == 1 && CMVerifierFixture.calls == 0)
        current.testDispose(); UIApplication.shared.applicationState = .active
        current = SteamClientSignInSync(); sync = current; current.start(); await settle()
        precondition(current.phase == .synced && SteamSignIn.saved != nil)
        print("PASS: a protected pending transfer survives app restart and validates without launching Windows again")

        current = fresh(); SteamSignIn.canStore = false
        let old = token(label: "older_native_fixture"); SteamSignIn.saved = ("fixture_user", old, "")
        current.receive(data); await settle()
        precondition(current.phase == .retrying && SteamSignIn.saved?.refreshToken == old)
        SteamSignIn.canStore = true; current.testTick(); await settle(); precondition(current.phase == .synced)
        current = fresh(); SteamClientPendingStore.writable = false; UIApplication.shared.applicationState = .inactive
        current.receive(data); precondition(SteamClientPendingStore.values.isEmpty)
        SteamClientPendingStore.writable = true; UIApplication.shared.applicationState = .active; current.testTick(); await settle()
        precondition(current.phase == .synced)
        print("PASS: Keychain failure preserves an existing sign-in and retries after storage becomes available")

        current = fresh(); CMVerifierFixture.mode = .hold; current.receive(data); await settle()
        precondition(CMVerifierFixture.waiting != nil); SteamSignIn.signOut(); CMVerifierFixture.release(); await settle()
        precondition(SteamSignIn.saved == nil && SteamClientPendingStore.values.isEmpty)
        current.receive(data); await settle(); precondition(SteamSignIn.saved == nil)
        current.beginSteamSession(); CMVerifierFixture.mode = .success; current.receive(data); await settle()
        precondition(current.phase == .synced)
        print("PASS: App sign-out cancels stale import and blocks reimport until the user starts a new Windows session")

        current = fresh(); CMVerifierFixture.mode = .hold; current.receive(data); await settle()
        let manual = token(subject: candidate.subject + 1, label: "manual_fixture")
        _ = SteamSignIn.store(accountName: "manual_fixture", refreshToken: manual, accessToken: "")
        await settle(); CMVerifierFixture.release(); await settle()
        precondition(SteamSignIn.saved?.refreshToken == manual)
        print("PASS: a manual App login wins over an older in-flight Windows authorization import")

        current = fresh(); CMVerifierFixture.mode = .hold; current.receive(data); await settle()
        try account(candidate.subject + 1); CMVerifierFixture.release(); await settle()
        precondition(SteamSignIn.saved == nil)
        CMVerifierFixture.mode = .success; current.receive(Data(token(subject: candidate.subject + 1).utf8)); await settle()
        precondition(SteamClientSignInRules.claims(SteamSignIn.saved!.refreshToken)?["sub"] as? String == String(candidate.subject + 1))
        current.testDispose()
        print("PASS: changing Windows accounts invalidates an older validation response; only the newly selected account imports")

        // The manual button must never turn account metadata into a sign-in.
        current = fresh(); try account()
        current.rereadInstalledSignIn(); await settle()
        precondition(current.rereadNotice != nil && CMVerifierFixture.calls == 0 && SteamSignIn.saved == nil)
        let executable = root.appendingPathComponent(SteamClient.clientDirectory + "/Steam.exe")
        try Data([0x4d,0x5a]).write(to: executable)
        current = fresh(); current.rereadInstalledSignIn(); await settle()
        precondition(current.phase == .waitingForToken && current.rereadNotice != nil && SteamSignIn.saved == nil && CMVerifierFixture.calls == 0)
        print("PASS: manual reread reports missing installation/no captured authorization; loginusers alone cannot sign in")

        current = fresh(); SteamSignIn.signOut(); await settle()
        SteamClientPendingStore.values = [candidate]
        current.rereadInstalledSignIn(); await settle()
        precondition(current.phase == .synced && current.statusText != nil && SteamSignIn.saved?.refreshToken == refresh)
        precondition(!UserDefaults.standard.bool(forKey: key) && CMVerifierFixture.calls == 1)
        current = fresh(); SteamSignIn.saved = ("fixture_user", refresh, "")
        current.rereadInstalledSignIn(); await settle()
        precondition(current.phase == .synced && CMVerifierFixture.calls == 1)
        print("PASS: explicit manual retry restores protected handoff or revalidates matching App authorization; success still requires CM")

        current = fresh(); SteamClientPendingStore.values = [candidate]; CMVerifierFixture.mode = .hold
        current.rereadInstalledSignIn(); await settle()
        precondition(current.phase == .validating && CMVerifierFixture.calls == 1)
        current.rereadInstalledSignIn(); await settle()
        precondition(CMVerifierFixture.calls == 1)
        CMVerifierFixture.release(); await settle(); precondition(current.phase == .synced)
        current = fresh(); SteamClientPendingStore.values = [candidate]; LibraryModel.shared.current = 1
        current.rereadInstalledSignIn(); await settle()
        precondition(current.phase == .waitingForWindows && CMVerifierFixture.calls == 0)
        LibraryModel.shared.current = nil; current.testTick(); await settle()
        precondition(current.phase == .synced)
        print("PASS: repeated clicks share one verification; manual reread waits for Windows instead of starting a second CM session")

        let client32 = root.appendingPathComponent("Program Files/Steam Client32")
        try FileManager.default.createDirectory(at: client32.appendingPathComponent("config"), withIntermediateDirectories: true)
        try Data([0x4d,0x5a]).write(to: client32.appendingPathComponent("steam.exe"))
        current = fresh(); SteamClient.clientDirectory = "Program Files/Steam Client32"
        SteamClientPendingStore.values = [candidate]
        current.rereadInstalledSignIn(); await settle()
        precondition(current.phase == .synced && SteamSignIn.saved?.refreshToken == refresh)
        let login32 = client32.appendingPathComponent("config/loginusers.vdf")
        try "\"users\" { \"\(candidate.subject + 1)\" { \"AccountName\" \"fixture_32\" \"MostRecent\" \"1\" } }"
            .write(to: login32, atomically: true, encoding: .utf8)
        current = fresh(); SteamClient.clientDirectory = "Program Files/Steam Client32"
        SteamClientPendingStore.values = [candidate]
        current.rereadInstalledSignIn(); await settle()
        precondition(SteamSignIn.saved == nil && CMVerifierFixture.calls == 0 && current.rereadNotice != nil)
        SteamSignIn.saved = ("fixture_user", refresh, "")
        current.rereadInstalledSignIn(); await settle()
        precondition(SteamSignIn.saved?.refreshToken == refresh && CMVerifierFixture.calls == 0)
        SteamSignIn.saved = nil
        let refresh32 = token(subject: candidate.subject + 1, label: "client32_fixture")
        let candidate32 = SteamClientSignInRules.candidate(Data(refresh32.utf8))!
        SteamClientPendingStore.values = [candidate32]
        current.rereadInstalledSignIn(); await settle()
        precondition(current.phase == .synced && SteamSignIn.saved?.refreshToken == refresh32)
        print("PASS: other installed architecture is a metadata fallback; a selected client's different account is never replaced by the other client's login")

        let ambiguous = "\"users\" { \"\(candidate.subject)\" { \"AccountName\" \"fixture_user\" \"MostRecent\" \"1\" } \"\(candidate.subject + 1)\" { \"AccountName\" \"fixture_32\" \"MostRecent\" \"1\" } }"
        precondition(SteamClientSignInRules.selectedAccount(loginUsers: Data(ambiguous.utf8)) == nil)
        try ambiguous.write(to: login32, atomically: true, encoding: .utf8)
        current = fresh(); SteamClient.clientDirectory = "Program Files/Steam Client32"
        SteamClientPendingStore.values = [candidate]
        current.rereadInstalledSignIn(); current.testTick(); await settle()
        precondition(SteamSignIn.saved == nil && CMVerifierFixture.calls == 0 && current.rereadNotice != nil)
        current = fresh(); SteamSignIn.enabled = false; SteamClientPendingStore.values = [candidate]
        current.rereadInstalledSignIn(); await settle()
        precondition(CMVerifierFixture.calls == 0 && SteamSignIn.saved == nil && current.rereadNotice != nil)
        current.testDispose(); SteamClient.clientDirectory = "Program Files/Steam Client"
        print("PASS: ambiguous account metadata and disabled sync never authorize an import")

        let library = AccountLibraryCheck()
        SteamSignIn.saved = ("old_fixture", "", "")
        let loading = Task { await library.refreshLibrary(interactive: false) }
        await settle(); precondition(library.fetcher.waiting != nil)
        SteamSignIn.saved = ("new_fixture", "", "")
        library.testAccountChanged()
        library.fetcher.waiting?.resume(returning: [.init(appID: 1, name: "old fixture")])
        library.fetcher.waiting = nil
        await loading.value; await settle()
        precondition(library.owned.map(\.name) == ["new fixture"] && library.writes == [["new fixture"]])
        precondition(library.session.logoffs == 1 && library.paused == [1] && library.resumeAfterSession.isEmpty)
        print("PASS: an old account's delayed library response cannot enter the new account's library or cache")
        precondition(SteamOwnedLibrary.shared.leases == 0)
    }
}
