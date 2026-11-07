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

    static func entry(install: Bool, appID: Int? = nil) -> LibraryEntry {
        let id = install ? installerID : clientID
        let path = install ? bootstrapPath : clientDirectory + "/" + (executableURL?.lastPathComponent ?? "Steam.exe")
        let saved = LibraryModel.shared.entries.first { $0.id == id }
        let global = LibraryModel.shared.entries.first { $0.id == clientID }
        let gameProfile = appID.flatMap { id in LibraryModel.shared.entries.first { $0.steamAppID == id } }
        let customized = gameProfile?.steamUseGlobalSettings == false ? gameProfile : nil
        var entry = customized ?? gameProfile ?? global ?? saved
            ?? LibraryEntry(title: install ? L("Steam installer") : "Steam", relativePath: path, bits: 32)
        if customized == nil, gameProfile != nil, let global { entry.inheritRuntimeSettings(from: global) }
        entry.id = id
        entry.relativePath = path
        entry.launchMode = "desktop"
        entry.startServices = true
        entry.steamClientAppID = appID
        entry.title = gameProfile?.title ?? (install ? L("Steam installer") : "Steam")
        entry.steamUseGlobalSettings = gameProfile?.steamUseGlobalSettings
        entry.steamSettingsPath = customized?.windowsPath ?? windowsExecutable
        entry.steamAppID = nil
        entry.bigPicture = nil
        entry.workingDirectory = nil
        // The controller supplies NSIS's final /D argument internally.
        if install { entry.arguments = "" }
        else {
            entry.arguments = launchArguments(appID: appID)
            if let url = executableURL, let inspected = try? LibraryModel.inspect(url) {
                entry.bits = inspected.bits
            }
        }
        normalizeLaunch(&entry)
        return entry
    }

    /// The same editor/profile as a library game's settings, with Steam-wide scope.
    static var settingsEntry: LibraryEntry {
        var profile = LibraryModel.shared.entries.first { $0.id == clientID }
            ?? LibraryModel.shared.entries.first { $0.id == installerID }
            ?? LibraryEntry(title: "Steam", relativePath: clientDirectory + "/Steam.exe", bits: 32)
        profile.id = clientID; profile.relativePath = clientDirectory + "/Steam.exe"
        profile.title = L("Steam settings")
        profile.steamAppID = nil; profile.steamClientAppID = nil; profile.steamSettingsPath = nil
        profile.steamUseGlobalSettings = nil
        profile.arguments = extraArguments
        return profile
    }

    static let bigPictureKey = "mdeck.steam.bigPicture"
    static let argumentsKey = "mdeck.steam.arguments"

    static var bigPicture: Bool {
        UserDefaults.standard.object(forKey: bigPictureKey) as? Bool ?? true
    }

    static var extraArguments: String {
        UserDefaults.standard.string(forKey: argumentsKey)
            ?? LibraryModel.shared.entries.first { $0.id == clientID && $0.steamClientAppID == nil }?.arguments
            ?? clientArguments
    }

    static func launchArguments(appID: Int? = nil) -> String {
        var arguments = compatibilityArguments(extraArguments)
        // The explicit preference owns the mode; the editable field cannot
        // silently override it or carry a stale game's launch request.
        arguments = removingLaunchRequests(arguments)
        if bigPicture { arguments += " -gamepadui" }
        if let appID, appID > 0, UInt64(appID) < UInt64(UInt32.max) {
            arguments += " -applaunch \(appID)"
            if let game = LibraryModel.shared.entries.first(where: { $0.steamAppID == appID }), !game.arguments.isEmpty {
                arguments += " " + game.arguments
            }
        }
        return arguments
    }

    private static func removingLaunchRequests(_ value: String) -> String {
        // Keep each token's original quotes and escapes. A quoted path with
        // spaces must survive, while stale launch selectors must not leak
        // from the previous game into a fresh client launch.
        var tokens: [String] = [], token = "", quoted = false, slashes = 0
        for character in value {
            if character == "\"", slashes % 2 == 0 { quoted.toggle() }
            if character.isWhitespace && !quoted {
                if !token.isEmpty { tokens.append(token); token = "" }
            } else { token.append(character) }
            slashes = character == "\\" ? slashes + 1 : 0
        }
        if !token.isEmpty { tokens.append(token) }
        var kept: [String] = [], skip = false
        for token in tokens {
            if skip { skip = false; continue }
            let key = token.replacingOccurrences(of: "\"", with: "").lowercased()
            if key == "-applaunch" { skip = true; continue }
            if ["-bigpicture", "-gamepadui"].contains(key) || key.hasPrefix("steam://") { continue }
            kept.append(token)
        }
        return kept.joined(separator: " ")
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
        // Rebuild from persistent global/game preferences each time. Reusing
        // the previous child rule can leak that game's flags to another game.
        let childArguments = launchArguments(appID: entry.steamClientAppID)
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
            try registerLibraries()
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
        try data.write(to: target, options: .atomic)
        guard let helper = Bundle.main.url(forResource: "SteamBootstrap", withExtension: "exe", subdirectory: "BundledInstallers") else {
            throw LibraryError.message(L("The Steam preparation controller is missing. Install a complete IPA."))
        }
        try Data(contentsOf: helper).write(to: destination(bootstrapPath), options: .atomic)
        try stageInstallationLibraries()
        try prepareInstallationDirectory()
        for name in ["SteamBootstrap.state", "SteamBootstrap.state.tmp", "SteamBootstrap.cancel"] {
            let file = try destination("Madeira/Installers/" + name)
            if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
        }
        winios_steam_setup_reset()
        LogStore.shared.log("[steam-installer] verified bundled setup; route=session-controller; installer UI covered; bits=32")
    }

    static func stagedLibrariesPath(_ section: String) -> String {
        "Madeira/Installers/SteamLibraries." + section + ".vdf"
    }

    private static var libraryRoots: [String] {
        MadeiraDock.steamLibraries(drive: LibraryModel.drive).compactMap { library in
            guard library.hasSuffix("/steamapps") else { return nil }
            return String(library.dropLast("/steamapps".count))
        }
    }

    /// NSIS requires an empty target. The controller installs these snapshots
    /// only after SteamSetup exits, before starting Steam in the same session.
    static func stageInstallationLibraries() throws {
        let paths = libraryRoots
        for section in ["config", "steamapps"] {
            let source = try destination(clientDirectory + "/" + section + "/libraryfolders.vdf")
            let existing = FileManager.default.fileExists(atPath: source.path) ? try Data(contentsOf: source) : nil
            let data = try ExternalSteamLibraries.add(paths: paths, to: existing)
            let staged = try destination(stagedLibrariesPath(section))
            try FileManager.default.createDirectory(at: staged.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: staged, options: .atomic)
        }
    }

    /// Recover Build 20's metadata-only target without deleting anything.
    /// Any actual installation/game content remains untouched and blocks setup.
    static func prepareInstallationDirectory() throws {
        let fm = FileManager.default
        let folder = try destination(clientDirectory)
        if fm.fileExists(atPath: folder.path) {
            let entries = try fm.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey])
            if !entries.isEmpty {
                for directory in entries {
                    let values = try directory.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
                    guard ["config", "steamapps"].contains(directory.lastPathComponent.lowercased()),
                          values.isDirectory == true, values.isSymbolicLink != true else {
                        throw LibraryError.message(L("The Steam folder contains existing files but Steam.exe is missing. Preserve or move that folder before installing Steam."))
                    }
                    for file in try fm.contentsOfDirectory(at: directory, includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey]) {
                        let values = try file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
                        guard file.lastPathComponent.lowercased() == "libraryfolders.vdf",
                              values.isRegularFile == true, values.isSymbolicLink != true else {
                            throw LibraryError.message(L("The Steam folder contains existing files but Steam.exe is missing. Preserve or move that folder before installing Steam."))
                        }
                    }
                }
                let backup = try destination("Madeira/Installers/SteamClient-metadata-" + UUID().uuidString + ".backup")
                try fm.createDirectory(at: backup.deletingLastPathComponent(), withIntermediateDirectories: true)
                try fm.moveItem(at: folder, to: backup)
                LogStore.shared.log("[steam-installer] preserved metadata-only target as " + backup.lastPathComponent)
            }
        }
        try fm.createDirectory(at: folder, withIntermediateDirectories: true)
    }

    /// Let Valve's interactive client see games downloaded by mdeck and the
    /// connected libraries too. Preserve its existing VDF entries.
    static func registerLibraries() throws {
        // A running client owns these files. A launch preflight registers again
        // after the session ends if a native download was finishing as it began.
        guard installed, wine_process_is_running() == 0, wineserver_is_running() == 0 else { return }
        let paths = libraryRoots
        for sub in ["config", "steamapps"] {
            let file = try destination(clientDirectory + "/" + sub + "/libraryfolders.vdf")
            let existing = FileManager.default.fileExists(atPath: file.path) ? try Data(contentsOf: file) : nil
            let data = try ExternalSteamLibraries.add(paths: paths, to: existing)
            if data != existing {
                try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
                try data.write(to: file, options: .atomic)
            }
        }
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

/// Global preferences shared by the home button, setup handoff and game cards.
struct SteamClientLaunchSettings: View {
    @AppStorage(SteamClient.bigPictureKey) private var bigPicture = true
    @State private var arguments = SteamClient.extraArguments
    @State private var invalidArguments = false

    var body: some View {
        Section {
            Toggle("Start Steam in Big Picture mode", isOn: $bigPicture)
            TextField("Steam launch arguments", text: $arguments, axis: .vertical)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                .onChange(of: arguments) { _, value in
                    invalidArguments = !LaunchArgumentText.valid(value)
                    if !invalidArguments { UserDefaults.standard.set(value, forKey: SteamClient.argumentsKey) }
                }
            if invalidArguments {
                Text("Use balanced double quotes, no control characters, and at most 64 launch arguments in 4 KB.")
                    .font(.caption).foregroundStyle(.orange)
            }
            Button("Reset Steam launch arguments") {
                arguments = SteamClient.clientArguments
                UserDefaults.standard.set(arguments, forKey: SteamClient.argumentsKey)
            }
        } header: { Text("Steam startup") } footer: {
            Text("These global options apply to Start Steam and games launched from the library. Required compatibility options are always included. Changes apply to the next session.")
        }
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
