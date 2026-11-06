import SwiftUI
import CryptoKit

/// The interactive Windows client has its own directory. Never start or update
/// the pinned client in SteamRuntimeFiles.relativeRoot used by Madeira Dock.
enum SteamClient {
    static let installerID = UUID(uuidString: "E11F2D61-367D-46D3-8521-AE5B97C36E14")!
    static let clientID = UUID(uuidString: "51DFB51A-09B1-4A41-9B55-613A652F7796")!
    static let installerPath = "Madeira/Installers/SteamSetup.exe"
    static let clientDirectory = "Program Files/Steam Client"
    static let clientPath = clientDirectory + "/steam.exe"
    static let windowsDirectory = "C:\\Program Files\\Steam Client"
    static let clientArguments = "-no-cef-sandbox -cef-disable-gpu -console -nocrashmonitor -cef-disable-features=SegmentationPlatform,OptimizationTargetPrediction,OptimizationHints"
    static let installerSHA256 = "7d3654531c32d941b8cae81c4137fc542172bfa9635f169cb392f245a0a12bcb"

    static func owns(_ entry: LibraryEntry) -> Bool {
        entry.id == installerID || entry.id == clientID
    }

    static var installed: Bool {
        guard let url = try? destination(clientPath) else { return false }
        return FileManager.default.fileExists(atPath: url.path)
    }

    static func entry(install: Bool) -> LibraryEntry {
        let id = install ? installerID : clientID
        let path = install ? installerPath : clientPath
        let saved = LibraryModel.shared.entries.first { $0.id == id }
        var entry = saved
            ?? LibraryEntry(title: install ? L("Steam installer") : "Steam", relativePath: path, bits: 32)
        entry.id = id
        entry.relativePath = path
        entry.launchMode = "desktop"
        entry.startServices = true
        // NSIS requires /D to be the final argument, without quotes, even with spaces.
        if install { entry.arguments = "/D=" + windowsDirectory }
        else {
            if saved == nil { entry.arguments = clientArguments }
            if let url = try? destination(path), let inspected = try? LibraryModel.inspect(url) {
                entry.bits = inspected.bits
            }
        }
        normalizeLaunch(&entry)
        return entry
    }

    /// Start the installer as explorer's direct child. The generic services
    /// batch exited in cmd.exe before creating SteamSetup on the first iPad
    /// test. NSIS can request its own services while installing; an otherwise
    /// empty desktop does not need a shell script to open its initial window.
    static func normalizeLaunch(_ entry: inout LibraryEntry) {
        guard entry.id == installerID else { return }
        entry.launchMode = "desktop"
        entry.startServices = false
    }

    /// Called after the ordinary session/JIT checks, before executable validation.
    static func prepare(_ entry: LibraryEntry) throws {
        guard owns(entry) else { return }
        guard wine_process_is_running() == 0, wineserver_is_running() == 0 else {
            throw LibraryError.message(L("A session is already running."))
        }
        if entry.id == clientID {
            guard entry.relativePath == clientPath, installed else {
                throw LibraryError.message(L("Install Steam first, then use Start Steam."))
            }
            return
        }
        guard entry.relativePath == installerPath,
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
        LogStore.shared.log("[steam-installer] verified bundled SteamSetup.exe; route=explorer-direct; services-batch=off; bits=32")
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
                    Text("The official Windows installer is included. It needs an internet connection to download the Steam client. Complete installation in the Wine desktop, keeping the suggested folder, then return here to start Steam.")
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
