// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
import Foundation
import CryptoKit

/// Candidates are not authorization. Only Valve accepting the refresh token
/// and returning an access token for the same account permits a Keychain import.
enum SteamClientSignInRules {
    struct Candidate: Codable, Equatable {
        let refresh: String
        let subject: UInt64
        let expires: Date
        let received: Date
        var fingerprint: String { SHA256.hash(data: Data(refresh.utf8)).map { String(format: "%02x", $0) }.joined() }
    }
    struct Account: Equatable { let name: String; let subject: UInt64 }
    struct Verified { let refresh: String; let access: String }

    static func claims(_ token: String) -> [String: Any]? {
        guard token.utf8.count <= 8192 else { return nil }
        let parts = token.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 3, parts.allSatisfy({ !$0.isEmpty }), parts[1].count <= 8192 else { return nil }
        var body = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        body += String(repeating: "=", count: (4 - body.count % 4) % 4)
        guard let data = Data(base64Encoded: body) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }
    static func identity(_ token: String, audience: String, now: Date) -> (UInt64, Date)? {
        guard let json = claims(token), json["iss"] as? String == "steam",
              let sub = json["sub"] as? String, let subject = UInt64(sub),
              subject >> 32 == 0x01100001, subject & 0xffffffff != 0,
              let audiences = json["aud"] as? [String], audiences.contains(audience),
              let exp = json["exp"] as? NSNumber, exp.doubleValue.isFinite else { return nil }
        let expires = Date(timeIntervalSince1970: exp.doubleValue)
        return expires.timeIntervalSince(now) > 30 ? (subject, expires) : nil
    }
    static func candidate(_ data: Data, now: Date = Date()) -> Candidate? {
        guard !data.isEmpty, data.count <= 16386 else { return nil }
        var bytes = Data(data)
        let utf16 = bytes.count >= 6 && bytes[0] == 101 && bytes[1] == 0 && bytes[2] == 121 && bytes[3] == 0
        if utf16 {
            if bytes.count >= 2 && bytes.suffix(2) == Data([0, 0]) { bytes.removeLast(2) }
        } else if bytes.last == 0 { bytes.removeLast() }
        guard let refresh = String(data: bytes, encoding: utf16 ? .utf16LittleEndian : .utf8),
              let (subject, expires) = identity(refresh, audience: "renew", now: now) else { return nil }
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
    /// Valve's public CAuthentication_AccessToken_GenerateForApp request:
    /// refresh_token=1, fixed64 steamid=2, renewal_type omitted (None).
    static func validationRequest(_ candidate: Candidate) -> Data {
        var encoder = ProtobufEncoder()
        encoder.writeString(fieldNumber: 1, value: candidate.refresh)
        encoder.writeFixed64(fieldNumber: 2, value: candidate.subject)
        return encoder.data
    }
    static func verified(_ candidate: Candidate, response: Data, now: Date = Date()) -> Verified? {
        guard response.count <= 32768 else { return nil }
        var decoder = ProtobufDecoder(response), access = "", renewed = ""
        do {
            while let tag = try decoder.readTag() {
                if tag.fieldNumber == 1 && tag.wireType == .lengthDelimited { access = try decoder.readString() }
                else if tag.fieldNumber == 2 && tag.wireType == .lengthDelimited { renewed = try decoder.readString() }
                else { try decoder.skip(wireType: tag.wireType) }
            }
        } catch { return nil }
        let refresh = renewed.isEmpty ? candidate.refresh : renewed
        guard identity(access, audience: "web", now: now)?.0 == candidate.subject,
              identity(refresh, audience: "renew", now: now)?.0 == candidate.subject else { return nil }
        return Verified(refresh: refresh, access: access)
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
        return Array(values.filter { SteamClientSignInRules.identity($0.refresh, audience: "renew", now: Date())?.0 == $0.subject }.prefix(4))
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
    enum Phase { case idle, waitingForAccount, validating, synced, retrying, failed }
    @Published private(set) var phase: Phase = .idle
    private let suppressedKey = "mdeck.steam.client-signin.suppressed"
    private var pending: [SteamClientSignInRules.Candidate] = []
    private var pendingStored = true
    private var task: Task<Void, Never>?
    private var timer: Timer?
    private var revision = UUID()
    private var retryAt = Date.distantPast
    private var started = false
    private var importedFingerprint: String?
    private var observers: [NSObjectProtocol] = []
    private var loginURL: URL { LibraryModel.drive.appendingPathComponent(SteamClient.clientDirectory + "/config/loginusers.vdf") }

    func start() {
        guard !started else { return }; started = true
        pending = SteamClientPendingStore.load()
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
        UserDefaults.standard.removeObject(forKey: suppressedKey)
        retryAt = .distantPast
        wake()
    }
    func receive(_ data: Data) {
        start()
        guard SteamSignIn.flag("MADEIRA_STEAM_SIGNIN_SYNC", default: true),
              !UserDefaults.standard.bool(forKey: suppressedKey),
              let candidate = SteamClientSignInRules.candidate(data) else { return }
        if let native = SteamSignIn.credentialsForDock(), native.refreshToken == candidate.refresh,
           account(for: candidate)?.name.caseInsensitiveCompare(native.accountName) == .orderedSame {
            phase = .synced; return
        }
        guard !pending.contains(where: { $0.fingerprint == candidate.fingerprint }) else { return }
        pending.removeAll { $0.subject == candidate.subject }
        pending.insert(candidate, at: 0); pending = Array(pending.prefix(4))
        pendingStored = SteamClientPendingStore.save(pending)
        revision = UUID(); task?.cancel(); task = nil; retryAt = .distantPast
        phase = .waitingForAccount
        wake()
    }
    private func signOut() {
        UserDefaults.standard.set(true, forKey: suppressedKey)
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
              UIApplication.shared.applicationState == .active, task == nil, Date() >= retryAt else { return }
        let count = pending.count
        pending.removeAll { $0.expires <= Date() }
        if count != pending.count { pendingStored = false }
        if !pendingStored { pendingStored = SteamClientPendingStore.save(pending) }
        guard !pending.isEmpty else { SteamClientPendingStore.save([]); timer?.invalidate(); timer = nil; return }
        guard let selection = pending.compactMap({ candidate in account(for: candidate).map { (candidate, $0) } }).first else {
            phase = .waitingForAccount; return
        }
        let (candidate, account) = selection, attempt = revision
        let before = SteamSignIn.credentialsForDock()?.refreshToken
        phase = .validating
        task = Task { @MainActor in
            defer { if revision == attempt { task = nil } }
            do {
                // HTTPS token verification creates no competing CM logon.
                let response = try await SteamAuthAPI.call("GenerateAccessTokenForApp", body: SteamClientSignInRules.validationRequest(candidate))
                guard !Task.isCancelled, revision == attempt,
                      !UserDefaults.standard.bool(forKey: suppressedKey),
                      self.account(for: candidate) == account,
                      SteamSignIn.credentialsForDock()?.refreshToken == before else { return }
                guard let verified = SteamClientSignInRules.verified(candidate, response: response) else {
                    reject(candidate); return
                }
                importedFingerprint = SHA256.hash(data: Data(verified.refresh.utf8)).map { String(format: "%02x", $0) }.joined()
                guard SteamSignIn.store(accountName: account.name, refreshToken: verified.refresh, accessToken: verified.access) else {
                    phase = .retrying; retryAt = Date().addingTimeInterval(60)
                    SteamLog.event("[steam-signin-sync] waiting for Keychain storage")
                    return
                }
                pending = []; SteamClientPendingStore.save([])
                timer?.invalidate(); timer = nil; phase = .synced
                SteamLog.event("[steam-signin-sync] Windows Steam authorization verified and imported")
            } catch is CancellationError {
            } catch {
                guard revision == attempt else { return }
                if let error = error as? SteamError, [.invalidCredentials, .authSessionExpired, .accountDisabled].contains(error) { reject(candidate) }
                else {
                    phase = .retrying; retryAt = Date().addingTimeInterval(60)
                    SteamLog.event("[steam-signin-sync] verification unavailable; retry scheduled")
                }
            }
        }
    }
    private func reject(_ candidate: SteamClientSignInRules.Candidate) {
        pending.removeAll { $0.fingerprint == candidate.fingerprint }
        pendingStored = SteamClientPendingStore.save(pending); phase = .failed
        if pending.isEmpty { timer?.invalidate(); timer = nil }
        SteamLog.event("[steam-signin-sync] Steam authorization could not be verified")
    }

    var statusText: String? {
        switch phase {
        case .idle, .synced: return nil
        case .waitingForAccount: return L("Waiting for Windows Steam to finish saving the sign-in…")
        case .validating: return L("Syncing the Steam sign-in…")
        case .retrying: return L("Steam sign-in sync is waiting and will retry automatically.")
        case .failed: return L("Steam sign-in could not be synced. Open Windows Steam and try again.")
        }
    }
}

@_cdecl("madeira_steam_token_received")
func madeiraSteamTokenReceived(_ bytes: UnsafeRawPointer?, _ count: UInt32) {
    guard let bytes, count > 0, count <= 16386 else { return }
    let data = Data(bytes: bytes, count: Int(count))
    Task { @MainActor in SteamClientSignInSync.shared.receive(data) }
}
#endif
