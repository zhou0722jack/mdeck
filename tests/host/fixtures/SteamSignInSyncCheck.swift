import Foundation
import Combine
import CryptoKit

@MainActor final class UIApplication {
    static let shared = UIApplication()
    enum State { case active, inactive }
    var applicationState = State.active
    static let didBecomeActiveNotification = Notification.Name("FixtureActive")
}
enum LibraryModel { static var drive = URL(fileURLWithPath: "/tmp") }
enum SteamClient { static let clientDirectory = "Program Files/Steam Client" }
enum SteamLog { static func event(_ value: String) {} }
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
func token(subject: UInt64 = 0x0110000100000001, audience: String = "renew", expires: Date = Date().addingTimeInterval(86400), label: String = "fixture") -> String {
    func encode(_ data: Data) -> String { data.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "") }
    let header = Data(#"{"alg":"RS256","typ":"JWT"}"#.utf8)
    let body = try! JSONSerialization.data(withJSONObject: ["iss":"steam", "sub":String(subject), "aud":[audience], "exp":expires.timeIntervalSince1970, "jti":label], options: .sortedKeys)
    return encode(header) + "." + encode(body) + ".synthetic_signature"
}
@MainActor enum SteamAuthAPI {
    enum Mode { case success, denied, offline, hold, wrongAccount }
    static var mode = Mode.success, calls = 0
    static var waiting: CheckedContinuation<Data, Error>?
    static func response(subject: UInt64) -> Data {
        var encoder = ProtobufEncoder()
        encoder.writeString(fieldNumber: 1, value: token(subject: subject, audience: "web"))
        return encoder.data
    }
    static func call(_ method: String, body: Data) async throws -> Data {
        precondition(method == "GenerateAccessTokenForApp")
        calls += 1
        var decoder = ProtobufDecoder(body), subject: UInt64 = 0
        while let tag = try decoder.readTag() {
            if tag.fieldNumber == 2 { precondition(tag.wireType == .fixed64); subject = try decoder.readFixed64() }
            else { try decoder.skip(wireType: tag.wireType) }
        }
        switch mode {
        case .denied: throw SteamError.invalidCredentials
        case .offline: throw URLError(.networkConnectionLost)
        case .hold: return try await withCheckedThrowingContinuation { waiting = $0 }
        case .wrongAccount: return response(subject: subject + 1)
        case .success: return response(subject: subject)
        }
    }
    static func release(subject: UInt64 = 0x0110000100000001) {
        let saved = waiting; waiting = nil; saved?.resume(returning: response(subject: subject))
    }
}

// PRODUCTION_MODEL

// PRODUCTION_LIBRARY_ACCOUNT_TEST

extension SteamClientSignInSync {
    func testTick() { retryAt = .distantPast; tick() }
    func testDispose() {
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
            SteamAuthAPI.mode = .success; SteamAuthAPI.calls = 0; UIApplication.shared.applicationState = .active
            let next = SteamClientSignInSync(); sync = next; next.beginSteamSession(); return next
        }
        let refresh = token(), data = Data(refresh.utf8)
        let candidate = SteamClientSignInRules.candidate(data)!
        precondition(SteamClientSignInRules.candidate(Data("password fixture".utf8)) == nil)
        precondition(SteamClientSignInRules.candidate(Data(token(audience: "web").utf8)) == nil)
        precondition(SteamClientSignInRules.candidate(Data(token(expires: .distantPast).utf8)) == nil)
        precondition(SteamClientSignInRules.candidate(Data(repeating: 65, count: 20000)) == nil)
        precondition(SteamClientSignInRules.candidate(Data((refresh + "\0").utf8))?.refresh == refresh)
        precondition(SteamClientSignInRules.candidate((refresh + "\0").data(using: .utf16LittleEndian)!)?.refresh == refresh)
        precondition(SteamClientSignInRules.verified(candidate, response: SteamAuthAPI.response(subject: candidate.subject + 1)) == nil)
        precondition(SteamClientSignInRules.verified(candidate, response: Data([10, 255, 255])) == nil)
        print("PASS: only bounded, unexpired refresh JWT candidates survive; UTF-8/UTF-16 and response account binding checked")

        try account(recent: false)
        var current = fresh(); current.receive(data); await settle()
        precondition(SteamSignIn.saved == nil && SteamAuthAPI.calls == 0 && current.phase == .waitingForAccount)
        try account(); current.testTick(); await settle()
        precondition(current.phase == .synced && SteamSignIn.saved?.refreshToken == refresh && SteamSignIn.stores == 1)
        current.receive(data); await settle(); precondition(SteamSignIn.stores == 1)
        precondition(SteamClientPendingStore.values.isEmpty)
        print("PASS: selected account plus Valve validation imports once and removes the pending transfer")

        current = fresh(); SteamAuthAPI.mode = .wrongAccount; current.receive(data); await settle()
        precondition(current.phase == .failed && SteamSignIn.saved == nil && SteamClientPendingStore.values.isEmpty)
        current = fresh(); SteamAuthAPI.mode = .denied; current.receive(data); await settle()
        precondition(current.phase == .failed && SteamSignIn.saved == nil)
        current = fresh(); SteamAuthAPI.mode = .offline; current.receive(data); await settle()
        precondition(current.phase == .retrying && SteamSignIn.saved == nil && SteamClientPendingStore.values.count == 1)
        SteamAuthAPI.mode = .success; current.testTick(); await settle(); precondition(current.phase == .synced)
        print("PASS: denied/mismatched tokens never sign in; temporary transport failure retries without losing the candidate")

        current = fresh(); UIApplication.shared.applicationState = .inactive; current.receive(data)
        precondition(SteamClientPendingStore.values.count == 1 && SteamAuthAPI.calls == 0)
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

        current = fresh(); SteamAuthAPI.mode = .hold; current.receive(data); await settle()
        precondition(SteamAuthAPI.waiting != nil); SteamSignIn.signOut(); SteamAuthAPI.release(); await settle()
        precondition(SteamSignIn.saved == nil && SteamClientPendingStore.values.isEmpty)
        current.receive(data); await settle(); precondition(SteamSignIn.saved == nil)
        current.beginSteamSession(); SteamAuthAPI.mode = .success; current.receive(data); await settle()
        precondition(current.phase == .synced)
        print("PASS: App sign-out cancels stale import and blocks reimport until the user starts a new Windows session")

        current = fresh(); SteamAuthAPI.mode = .hold; current.receive(data); await settle()
        let manual = token(subject: candidate.subject + 1, label: "manual_fixture")
        _ = SteamSignIn.store(accountName: "manual_fixture", refreshToken: manual, accessToken: "")
        await settle(); SteamAuthAPI.release(); await settle()
        precondition(SteamSignIn.saved?.refreshToken == manual)
        print("PASS: a manual App login wins over an older in-flight Windows authorization import")

        current = fresh(); SteamAuthAPI.mode = .hold; current.receive(data); await settle()
        try account(candidate.subject + 1); SteamAuthAPI.release(); await settle()
        precondition(SteamSignIn.saved == nil)
        SteamAuthAPI.mode = .success; current.receive(Data(token(subject: candidate.subject + 1).utf8)); await settle()
        precondition(SteamClientSignInRules.claims(SteamSignIn.saved!.refreshToken)?["sub"] as? String == String(candidate.subject + 1))
        current.testDispose()
        print("PASS: changing Windows accounts invalidates an older validation response; only the newly selected account imports")

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
    }
}
