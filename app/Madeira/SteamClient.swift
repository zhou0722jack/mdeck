import SwiftUI
import CryptoKit

/// The interactive Windows client has its own directory. Never start or update
/// the pinned client in SteamRuntimeFiles.relativeRoot used by Madeira Dock.
enum SteamClient {
    static let installerID = UUID(uuidString: "E11F2D61-367D-46D3-8521-AE5B97C36E14")!
    static let clientID = UUID(uuidString: "51DFB51A-09B1-4A41-9B55-613A652F7796")!
    static let installerPath = "Madeira/Installers/SteamSetup.exe"
    static let bootstrapPath = "Madeira/Installers/SteamBootstrap.exe"
    static let clientDirectory = "Program Files/Steam Client"
    static let clientPath = clientDirectory + "/steam.exe"
    static let windowsDirectory = "C:\\Program Files\\Steam Client"
    static let windowsExecutable = windowsDirectory + "\\Steam.exe"
    static let clientArguments = "-no-cef-sandbox -cef-disable-gpu -console -nocrashmonitor -cef-disable-features=SegmentationPlatform,OptimizationTargetPrediction,OptimizationHints"
    static let installerSHA256 = "7d3654531c32d941b8cae81c4137fc542172bfa9635f169cb392f245a0a12bcb"

    static func owns(_ entry: LibraryEntry) -> Bool {
        entry.id == installerID || entry.id == clientID
    }

    static var installed: Bool {
        executableURL != nil
    }

    /// Wine is case-insensitive, while the host drive may not be. NSIS writes
    /// Steam.exe and an updater can replace it with steam.exe.
    static var executableURL: URL? {
        guard let folder = try? destination(clientDirectory),
              let files = try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.isRegularFileKey]) else { return nil }
        return files.first { url in
            url.lastPathComponent.caseInsensitiveCompare("Steam.exe") == .orderedSame &&
                (try? url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true &&
                url.resolvingSymlinksInPath().path.hasPrefix(folder.resolvingSymlinksInPath().path + "/")
        }
    }

    static func entry(install: Bool) -> LibraryEntry {
        let id = install ? installerID : clientID
        let path = install ? bootstrapPath : clientDirectory + "/" + (executableURL?.lastPathComponent ?? "Steam.exe")
        let saved = LibraryModel.shared.entries.first { $0.id == id }
        var entry = saved
            ?? LibraryEntry(title: install ? L("Steam installer") : "Steam", relativePath: path, bits: 32)
        entry.id = id
        entry.relativePath = path
        entry.launchMode = "desktop"
        entry.startServices = true
        // The controller supplies NSIS's final /D argument internally.
        if install { entry.arguments = "" }
        else {
            entry.arguments = compatibilityArguments(saved?.arguments ?? "")
            if let url = executableURL, let inspected = try? LibraryModel.inspect(url) {
                entry.bits = inspected.bits
            }
        }
        normalizeLaunch(&entry)
        return entry
    }

    /// One controller owns the setup process and its successor. It preserves
    /// the server/JIT session instead of trying to initialize a second one.
    static func normalizeLaunch(_ entry: inout LibraryEntry) {
        guard entry.id == installerID else { return }
        entry.relativePath = bootstrapPath
        entry.arguments = ""
        entry.launchMode = "direct"
        entry.startServices = false
    }

    /// Native child spawning already supports an image-specific argument rule.
    /// Installers and Steam's updater otherwise launch steam.exe without the
    /// compatibility flags used by the home button. Preserve Steam-specific
    /// extra options while always supplying the required compatibility flags.
    static func configureSession(_ entry: LibraryEntry) {
        guard owns(entry) else { return }
        let existing = getenv("MADEIRA_CHILD_ARGS").map { String(cString: $0) } ?? ""
        let parts = existing.split(maxSplits: 1, whereSeparator: { $0.isWhitespace })
        let childArguments = parts.first?.lowercased() == "steam.exe" && parts.count == 2
            ? compatibilityArguments(String(parts[1])) : clientArguments
        setenv("MADEIRA_CHILD_ARGS", "steam.exe " + childArguments, 1)
        LogStore.shared.log("[steam-installer] Steam child/restart compatibility arguments enabled")
        setenv("MADEIRA_STEAM_AUTOINSTALL", entry.id == installerID ? "1" : "0", 1)
        if entry.id == installerID {
            setenv("MADEIRA_STEAM_CONTROLLED_SETUP", "1", 1)
            setenv("MADEIRA_WAIT_CHILDREN", "1", 1)
        } else { unsetenv("MADEIRA_STEAM_CONTROLLED_SETUP") }
        let automation = getenv("MADEIRA_STEAM_AUTOINSTALL").map { String(cString: $0) } ?? "unset"
        LogStore.shared.log("[steam-autoinstall] configured=" + automation)
    }

    static func compatibilityArguments(_ value: String) -> String {
        guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return clientArguments }
        var result = value
        var tokens: [String] = [], token = "", quoted = false
        for character in value {
            if character == "\"" { quoted.toggle() }
            else if character.isWhitespace && !quoted {
                if !token.isEmpty { tokens.append(token); token = "" }
            } else { token.append(character) }
        }
        if !token.isEmpty { tokens.append(token) }
        for flag in ["-no-cef-sandbox", "-cef-disable-gpu"] {
            if !tokens.contains(where: { $0.caseInsensitiveCompare(flag) == .orderedSame }) { result += " " + flag }
        }
        return result
    }

    static func cancelPreparation() {
        guard let url = try? destination("Madeira/Installers/SteamBootstrap.cancel") else { return }
        try? Data("cancel\n".utf8).write(to: url, options: .atomic)
    }

    static func preparationStatus() -> DeckSteamSetupStatus? {
        guard let url = try? destination("Madeira/Installers/SteamBootstrap.state"),
              let data = try? Data(contentsOf: url), data.count < 1024,
              let text = String(data: data, encoding: .utf8) else { return nil }
        var raw = winios_steam_setup_progress()
        winios_steam_setup_snapshot(&raw)
        return DeckSteamSetupStatus.decode(text, step: Int(raw.step), percent: Int(raw.percent), blocked: Int(raw.blocked))
    }

    /// Called after the ordinary session/JIT checks, before executable validation.
    static func prepare(_ entry: LibraryEntry) throws {
        guard owns(entry) else { return }
        guard wine_process_is_running() == 0, wineserver_is_running() == 0 else {
            throw LibraryError.message(L("A session is already running."))
        }
        if entry.id == clientID {
            guard entry.relativePath.caseInsensitiveCompare(clientPath) == .orderedSame, installed else {
                throw LibraryError.message(L("Install Steam first, then use Start Steam."))
            }
            return
        }
        guard entry.relativePath == bootstrapPath,
              let resource = Bundle.main.url(forResource: "SteamSetup", withExtension: "exe", subdirectory: "BundledInstallers") else {
            throw LibraryError.message(L("The bundled Steam installer is missing or damaged."))
        }
        let data = try Data(contentsOf: resource)
        guard SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == installerSHA256 else {
            throw LibraryError.message(L("The bundled Steam installer is missing or damaged."))
        }
        let target = try destination(installerPath)
        try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: destination(clientDirectory), withIntermediateDirectories: true)
        try data.write(to: target, options: .atomic)
        guard let helper = Bundle.main.url(forResource: "SteamBootstrap", withExtension: "exe", subdirectory: "BundledInstallers") else {
            throw LibraryError.message(L("The Steam preparation controller is missing. Install a complete IPA."))
        }
        try Data(contentsOf: helper).write(to: destination(bootstrapPath), options: .atomic)
        for name in ["SteamBootstrap.state", "SteamBootstrap.state.tmp", "SteamBootstrap.cancel"] {
            let file = try destination("Madeira/Installers/" + name)
            if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
        }
        winios_steam_setup_reset()
        LogStore.shared.log("[steam-installer] verified bundled setup; route=session-controller; installer UI covered; bits=32")
    }

    private static func destination(_ relative: String) throws -> URL {
        let root = LibraryModel.drive.resolvingSymlinksInPath().standardizedFileURL
        let target = root.appendingPathComponent(relative).resolvingSymlinksInPath().standardizedFileURL
        guard target.path.hasPrefix(root.path + "/") else {
            throw LibraryError.message(L("The Steam installer folder must stay inside Madeira's drive_c."))
        }
        return target
    }
}

struct SteamClientView: View {
    var launch: (LibraryEntry) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Button { launch(SteamClient.entry(install: false)) } label: {
                        Label("Start Steam", systemImage: "play.fill")
                    }
                    .disabled(!SteamClient.installed)
                    Button { launch(SteamClient.entry(install: true)) } label: {
                        Label("Run Steam installer", systemImage: "shippingbox")
                    }
                } footer: {
                    Text("Missing components are prepared first. If Steam.exe exists in the client folder, it starts with compatibility options. Otherwise setup runs behind the progress screen, closes, and Steam starts in the same session.")
                }
                Section {
                    Text(SteamClient.windowsDirectory).font(.footnote.monospaced()).textSelection(.enabled)
                } header: {
                    Text("Steam client folder")
                } footer: {
                    Text("This folder is separate from Madeira Dock's pinned Steam components. Do not select Madeira Dock's Steam folder in the installer.")
                }
                Section {
                    Text("Starting the installer or Steam uses the same JIT setup as a game. In external script mode, run Madeira's script in StikDebug first. Steam compatibility on this device still needs testing.")
                }
            }
            .modifier(DeckFormSkin())
            .navigationTitle("Steam")
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } } }
        }
    }
}
