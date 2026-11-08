// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
import Foundation
import CryptoKit

/// Candidates are not authorization. Valve's CM must accept the client
/// refresh token and return the same account before it becomes an App sign-in.
enum SteamClientSignInRules {
    struct Candidate: Codable, Equatable {
        let refresh: String
        let subject: UInt64
        let expires: Date
        let received: Date
        var fingerprint: String { SHA256.hash(data: Data(refresh.utf8)).map { String(format: "%02x", $0) }.joined() }
    }
    struct Account: Equatable { let name: String; let subject: UInt64 }

    static func claims(_ token: String) -> [String: Any]? {
        guard token.utf8.count <= 8192 else { return nil }
        let parts = token.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 3, parts.allSatisfy({ part in
            !part.isEmpty && part.utf8.allSatisfy { byte in
                (65...90).contains(byte) || (97...122).contains(byte) || (48...57).contains(byte) || byte == 45 || byte == 95
            }
        }) else { return nil }
        func object(_ part: Substring) -> [String: Any]? {
            var base64 = String(part).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
            base64 += String(repeating: "=", count: (4 - base64.count % 4) % 4)
            guard let data = Data(base64Encoded: base64) else { return nil }
            return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        }
        guard let header = object(parts[0]), let algorithm = header["alg"] as? String,
              !algorithm.isEmpty, algorithm.caseInsensitiveCompare("none") != .orderedSame else { return nil }
        return object(parts[1])
    }
    static func clientRefreshIdentity(_ token: String, now: Date) -> (UInt64, Date)? {
        guard let json = claims(token), json["iss"] as? String == "steam",
              let sub = json["sub"] as? String, let subject = UInt64(sub),
              subject >> 32 == 0x01100001, subject & 0xffffffff != 0,
              let audiences = json["aud"] as? [String],
              audiences.contains("client"), audiences.contains("derive"),
              let exp = json["exp"] as? NSNumber, exp.doubleValue.isFinite else { return nil }
        let expires = Date(timeIntervalSince1970: exp.doubleValue)
        return expires.timeIntervalSince(now) > 30 ? (subject, expires) : nil
    }
    static func candidate(_ data: Data, now: Date = Date()) -> Candidate? {
        guard !data.isEmpty, data.count <= 16386 else { return nil }
        var bytes = Data(data)
        // Base64url is ASCII. Do not assume any particular encoded JSON prefix.
        let utf16 = bytes.count >= 4 && bytes[0] != 0 && bytes[1] == 0 && bytes[2] != 0 && bytes[3] == 0
        if utf16 {
            if bytes.count >= 2 && bytes.suffix(2) == Data([0, 0]) { bytes.removeLast(2) }
        } else if bytes.last == 0 { bytes.removeLast() }
        guard let refresh = String(data: bytes, encoding: utf16 ? .utf16LittleEndian : .utf8),
              let (subject, expires) = clientRefreshIdentity(refresh, now: now) else { return nil }
        return Candidate(refresh: refresh, subject: subject, expires: expires, received: now)
    }
    /// loginusers supplies an account name, never a credential or proof of login.
    /// Only the selected/recent user may be paired with a captured token.
    static func account(_ candidate: Candidate, loginUsers: Data) -> Account? {
        guard var parser = try? SteamKeyValues(loginUsers), let tree = try? parser.read(),
              let users = tree["users"], let user = users[String(candidate.subject)],
              user["mostrecent"]?.string == "1", let name = user["accountname"]?.string,
              !name.isEmpty, name.utf8.count <= 128, !name.contains("\0"),
              name == name.trimmingCharacters(in: .whitespacesAndNewlines) else { return nil }
        return Account(name: name, subject: candidate.subject)
    }
    static func acceptsCMSubject(_ subject: UInt64, candidate: Candidate, now: Date = Date()) -> Bool {
        subject == candidate.subject && clientRefreshIdentity(candidate.refresh, now: now)?.0 == subject
    }
}

/// Private crypt32 ABI: NULL data carries one of these fixed stage codes.
/// No code contains a path, account identifier, data size or credential.
enum SteamClientAuthProbe: UInt32, CaseIterable {
    case monitorAttached = 1
    case interactiveSteam = 2
    case otherSteam = 3
    case webHelper = 4
    case otherProcess = 5
    case unknownProcess = 6
    case protectEntered = 7
    case unprotectEntered = 8
    case protectSucceeded = 9
    case unprotectSucceeded = 10
    case noJWT = 11
    case blobSkipped = 12

    var message: String {
        switch self {
        case .monitorAttached: return "[steam-signin-sync] Windows crypt32 monitor attached"
        case .interactiveSteam: return "[steam-signin-sync] Windows credential scope matched interactive Steam"
        case .otherSteam: return "[steam-signin-sync] Windows Steam is outside the supported installation path; transfer disabled"
        case .webHelper: return "[steam-signin-sync] Windows crypt32 attached to Steam webhelper; transfer disabled"
        case .otherProcess: return "[steam-signin-sync] Windows crypt32 attached to another process; transfer disabled"
        case .unknownProcess: return "[steam-signin-sync] Windows process identity unavailable; transfer disabled"
        case .protectEntered: return "[steam-signin-sync] Windows Steam entered CryptProtectData"
        case .unprotectEntered: return "[steam-signin-sync] Windows Steam entered CryptUnprotectData"
        case .protectSucceeded: return "[steam-signin-sync] Windows Steam CryptProtectData succeeded"
        case .unprotectSucceeded: return "[steam-signin-sync] Windows Steam CryptUnprotectData succeeded"
        case .noJWT: return "[steam-signin-sync] Windows Steam DPAPI data contained no complete JWT candidate"
        case .blobSkipped: return "[steam-signin-sync] Windows Steam DPAPI data skipped by buffer bounds"
        }
    }
}

#if canImport(UIKit)
import UIKit
import Security
import Combine

/// The pending transfer also stays in this device's Keychain. It survives an
/// app restart without a plaintext transfer file, command line or environment.
private enum SteamClientPendingStore {
    static let service = "mdeck.steam.client-signin.pending.v1"
    static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
         kSecAttrAccount as String: "pending"]
    }
    static func load() -> [SteamClientSignInRules.Candidate] {
        var q = query; q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data, data.count <= 100_000,
              let values = try? JSONDecoder().decode([SteamClientSignInRules.Candidate].self, from: data) else { return [] }
        return Array(values.filter { SteamClientSignInRules.clientRefreshIdentity($0.refresh, now: Date())?.0 == $0.subject }.prefix(4))
    }
    @discardableResult static func save(_ values: [SteamClientSignInRules.Candidate]) -> Bool {
        guard !values.isEmpty else {
            let status = SecItemDelete(query as CFDictionary)
            return status == errSecSuccess || status == errSecItemNotFound
        }
        guard let data = try? JSONEncoder().encode(Array(values.prefix(4))) else { return false }
        let attributes: [String: Any] = [kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        var status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound { status = SecItemAdd(query.merging(attributes) { _, new in new } as CFDictionary, nil) }
        return status == errSecSuccess
    }
}

@MainActor final class SteamClientSignInSync: ObservableObject {
    static let shared = SteamClientSignInSync()
    enum Phase { case idle, waitingForToken, waitingForAccount, waitingForWindows, validating, synced, retrying, failed }
    @Published private(set) var phase: Phase = .idle
    private let suppressedKey = "mdeck.steam.client-signin.suppressed"
    private var pending: [SteamClientSignInRules.Candidate] = []
    private var pendingStored = true
    private var task: Task<Void, Never>?
    private var verifier: SteamSession?
    private var closingTask: Task<Void, Never>?
    private var closingID = UUID()
    private var timer: Timer?
    private var revision = UUID()
    private var retryAt = Date.distantPast
    private var started = false
    private var importedFingerprint: String?
    private var reportedInvalidCandidate = false
    private var reportedProbeCodes: Set<UInt32> = []
    private var observers: [NSObjectProtocol] = []
    private var loginURL: URL { LibraryModel.drive.appendingPathComponent(SteamClient.clientDirectory + "/config/loginusers.vdf") }
    private var windowsRunning: Bool {
        LibraryModel.shared.current != nil || wine_process_is_running() != 0 || wineserver_is_running() != 0
    }

    func start() {
        guard !started else { return }; started = true
        pending = SteamClientPendingStore.load()
        SteamLog.event("[steam-signin-sync] bridge ready")
        if !pending.isEmpty { SteamLog.event("[steam-signin-sync] pending authorization restored") }
        observers.append(NotificationCenter.default.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.wake() }
        })
        observers.append(NotificationCenter.default.addObserver(forName: SteamSignIn.didSignOut, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.signOut() }
        })
        observers.append(NotificationCenter.default.addObserver(forName: SteamSignIn.didChange, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, let current = SteamSignIn.credentialsForDock() else { return }
                let fingerprint = SHA256.hash(data: Data(current.refreshToken.utf8)).map { String(format: "%02x", $0) }.joined()
                if fingerprint != self.importedFingerprint { self.signOut() }
            }
        })
        wake()
    }
    /// A user explicitly starts Steam/a desktop again after signing out in App.
    func beginSteamSession() {
        start()
        _ = closeVerifier()
        UserDefaults.standard.removeObject(forKey: suppressedKey)
        reportedInvalidCandidate = false
        reportedProbeCodes.removeAll()
        phase = pending.isEmpty ? .waitingForToken : .waitingForWindows
        SteamLog.event("[steam-signin-sync] waiting for Windows credential event")
        retryAt = .distantPast
        wake()
    }
    func receiveProbe(_ code: UInt32) {
        guard let probe = SteamClientAuthProbe(rawValue: code), reportedProbeCodes.insert(code).inserted else { return }
        SteamLog.event(probe.message)
    }
    func receive(_ data: Data) {
        start()
        guard SteamSignIn.flag("MADEIRA_STEAM_SIGNIN_SYNC", default: true) else {
            SteamLog.event("[steam-signin-sync] credential event ignored: sync disabled"); return
        }
        guard !UserDefaults.standard.bool(forKey: suppressedKey) else {
            SteamLog.event("[steam-signin-sync] credential event ignored: signed out in App"); return
        }
        guard let candidate = SteamClientSignInRules.candidate(data) else {
            if !reportedInvalidCandidate {
                reportedInvalidCandidate = true
                SteamLog.event("[steam-signin-sync] credential event rejected: invalid client refresh token shape")
            }
            return
        }
        if let native = SteamSignIn.credentialsForDock(), native.refreshToken == candidate.refresh,
           account(for: candidate)?.name.caseInsensitiveCompare(native.accountName) == .orderedSame {
            phase = .synced; return
        }
        guard !pending.contains(where: { $0.fingerprint == candidate.fingerprint }) else { return }
        pending.removeAll { $0.subject == candidate.subject }
        pending.insert(candidate, at: 0); pending = Array(pending.prefix(4))
        pendingStored = SteamClientPendingStore.save(pending)
        _ = closeVerifier()
        revision = UUID(); task?.cancel(); task = nil; retryAt = .distantPast
        phase = .waitingForAccount
        SteamLog.event("[steam-signin-sync] client refresh candidate accepted")
        wake()
    }
    private func signOut() {
        UserDefaults.standard.set(true, forKey: suppressedKey)
        _ = closeVerifier()
        revision = UUID(); task?.cancel(); task = nil; pending = []
        SteamClientPendingStore.save([]); timer?.invalidate(); timer = nil; phase = .idle
    }
    private func wake() {
        guard SteamSignIn.flag("MADEIRA_STEAM_SIGNIN_SYNC", default: true),
              !UserDefaults.standard.bool(forKey: suppressedKey), !pending.isEmpty else { return }
        if timer == nil {
            timer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in
                MainActor.assumeIsolated { self?.tick() }
            }
        }
        tick()
    }
    private func account(for candidate: SteamClientSignInRules.Candidate) -> SteamClientSignInRules.Account? {
        guard let handle = try? FileHandle(forReadingFrom: loginURL) else { return nil }
        defer { try? handle.close() }
        guard let data = try? handle.read(upToCount: 4 * 1024 * 1024 + 1), data.count <= 4 * 1024 * 1024 else { return nil }
        return SteamClientSignInRules.account(candidate, loginUsers: data)
    }
    private func tick() {
        guard SteamSignIn.flag("MADEIRA_STEAM_SIGNIN_SYNC", default: true),
              !UserDefaults.standard.bool(forKey: suppressedKey),
              UIApplication.shared.applicationState == .active, task == nil, closingTask == nil, Date() >= retryAt else { return }
        let count = pending.count
        pending.removeAll { $0.expires <= Date() }
        if count != pending.count { pendingStored = false }
        if !pendingStored { pendingStored = SteamClientPendingStore.save(pending) }
        guard !pending.isEmpty else {
            SteamClientPendingStore.save([]); timer?.invalidate(); timer = nil
            if count > 0 {
                phase = .failed
                SteamLog.event("[steam-signin-sync] pending authorization expired")
            }
            return
        }
        guard let selection = pending.compactMap({ candidate in account(for: candidate).map { (candidate, $0) } }).first else {
            if phase != .waitingForAccount { SteamLog.event("[steam-signin-sync] waiting for selected account metadata") }
            phase = .waitingForAccount; return
        }
        guard !windowsRunning else {
            if phase != .waitingForWindows { SteamLog.event("[steam-signin-sync] authorization saved; waiting for Windows session to end") }
            phase = .waitingForWindows; return
        }
        let (candidate, account) = selection, attempt = revision
        let before = SteamSignIn.credentialsForDock()?.refreshToken
        let cm = SteamSession(automaticallyReconnect: false)
        verifier = cm
        phase = .validating
        SteamLog.event("[steam-signin-sync] validating client authorization with Steam CM")
        task = Task { @MainActor in
            var leased = false, imported = false
            defer {
                if leased { SteamOwnedLibrary.shared.finishClientSignInVerification(imported: imported) }
                if verifier === cm { verifier = nil }
                if revision == attempt { task = nil }
            }
            do {
                await SteamOwnedLibrary.shared.prepareClientSignInVerification()
                leased = true
                guard !Task.isCancelled, revision == attempt, !windowsRunning else {
                    await cm.suspend(); return
                }
                try await cm.connectAndLogin(credentialsOverride: (account.name, candidate.refresh))
                let authenticated = cm.connectionState == .authenticated, reportedSubject = cm.steamID
                // Release this short-lived validation connection before the
                // downloader receives the login notification and connects.
                await cm.suspend()
                guard !Task.isCancelled, revision == attempt,
                      !UserDefaults.standard.bool(forKey: suppressedKey),
                      !windowsRunning,
                      self.account(for: candidate) == account,
                      SteamSignIn.credentialsForDock()?.refreshToken == before else { return }
                guard authenticated, SteamClientSignInRules.acceptsCMSubject(reportedSubject, candidate: candidate) else {
                    reject(candidate); return
                }
                importedFingerprint = candidate.fingerprint
                guard SteamSignIn.store(accountName: account.name, refreshToken: candidate.refresh, accessToken: "") else {
                    phase = .retrying; retryAt = Date().addingTimeInterval(60)
                    SteamLog.event("[steam-signin-sync] waiting for Keychain storage")
                    return
                }
                imported = true
                pending = []; SteamClientPendingStore.save([])
                timer?.invalidate(); timer = nil; phase = .synced
                SteamLog.event("[steam-signin-sync] Windows Steam authorization verified and imported")
            } catch is CancellationError {
                await cm.suspend()
            } catch {
                await cm.suspend()
                guard revision == attempt else { return }
                let permanent: Bool
                if case SteamError.logonDenied(let code) = error { permanent = SteamError.signInExpiredCodes.contains(code) }
                else if let steam = error as? SteamError { permanent = [.invalidCredentials, .authSessionExpired, .accountDisabled].contains(steam) }
                else { permanent = false }
                if permanent { reject(candidate) }
                else {
                    phase = .retrying; retryAt = Date().addingTimeInterval(60)
                    SteamLog.event("[steam-signin-sync] verification unavailable; retry scheduled")
                }
            }
        }
    }
    private func closeVerifier() -> Task<Void, Never>? {
        if let closingTask { return closingTask }
        guard let cm = verifier else { return nil }
        let running = task
        revision = UUID(); running?.cancel(); task = nil; verifier = nil
        let id = UUID(); closingID = id
        let stop = Task { @MainActor in await cm.suspend(); await running?.value }
        closingTask = stop
        Task { @MainActor in
            await stop.value
            if closingID == id { closingTask = nil }
        }
        return stop
    }
    /// runWineFullSequence calls this before starting any Windows processes.
    /// The retry closure checks that the selected session has not been cancelled.
    func deferWindowsLaunch(_ launch: @escaping @MainActor () -> Void) -> Bool {
        guard let stop = closeVerifier() else { return false }
        SteamLog.event("[steam-signin-sync] closing validation connection before Windows launch")
        Task { @MainActor in await stop.value; launch() }
        return true
    }
    private func reject(_ candidate: SteamClientSignInRules.Candidate) {
        pending.removeAll { $0.fingerprint == candidate.fingerprint }
        pendingStored = SteamClientPendingStore.save(pending); phase = .failed
        if pending.isEmpty { timer?.invalidate(); timer = nil }
        SteamLog.event("[steam-signin-sync] Steam authorization could not be verified")
    }

    var hasPendingAuthorization: Bool { !pending.isEmpty }
    var statusText: String? {
        switch phase {
        case .idle, .synced: return nil
        case .waitingForToken: return L("Waiting for Windows Steam sign-in authorization…")
        case .waitingForAccount: return L("Waiting for Windows Steam to finish saving the sign-in…")
        case .waitingForWindows: return L("Authorization received. End the Windows session to finish signing in here.")
        case .validating: return L("Syncing the Steam sign-in…")
        case .retrying: return L("Steam sign-in sync is waiting and will retry automatically.")
        case .failed: return L("Steam sign-in could not be synced. Open Windows Steam and try again.")
        }
    }
}

@_cdecl("madeira_steam_token_received")
func madeiraSteamTokenReceived(_ bytes: UnsafeRawPointer?, _ count: UInt32) {
    guard let bytes else {
        guard SteamClientAuthProbe(rawValue: count) != nil else { return }
        Task { @MainActor in SteamClientSignInSync.shared.receiveProbe(count) }
        return
    }
    guard count >= 128, count <= 16386 else { return }
    let data = Data(bytes: bytes, count: Int(count))
    Task { @MainActor in SteamClientSignInSync.shared.receive(data) }
}
#endif
