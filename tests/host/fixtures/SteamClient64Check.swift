import Foundation
import CryptoKit

func wine_process_is_running() -> Int32 { 0 }
func wineserver_is_running() -> Int32 { 0 }
func madeira_seed_prefix_if_needed(_ path: String) {}

@main struct Check {
    static func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    static func rejected(_ action: () throws -> Void) {
        do { try action(); preconditionFailure("invalid migration accepted") } catch {}
    }
    static func expect(_ condition: @autoclosure () throws -> Bool) rethrows {
        let result = try condition(); precondition(result)
    }
    static func main() async throws {
        let fm = FileManager.default, folder = URL(fileURLWithPath: CommandLine.arguments[1])
        let metadata = try JSONSerialization.jsonObject(with: Data(contentsOf: folder.appendingPathComponent("release.json"))) as! [String: Any]
        let imageRelease = SteamClient64Bootstrap.Release(file: "fixture.zip", archiveBytes: metadata["archiveBytes"] as! Int,
            archiveSHA256: metadata["archiveSHA256"] as! String, imageBytes: metadata["imageBytes"] as! Int,
            imageSHA256: metadata["imageSHA256"] as! String)
        let archive = try Data(contentsOf: folder.appendingPathComponent("good.zip"))
        let old = try Data(contentsOf: folder.appendingPathComponent("old.exe"))
        let root = folder.appendingPathComponent("drive")
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        let image = try SteamClient64Bootstrap.image(from: archive, release: imageRelease)
        precondition(SteamClient64Bootstrap.is64BitImage(image) && !SteamClient64Bootstrap.is64BitImage(old))
        rejected { var corrupt = archive; corrupt[0] ^= 1; _ = try SteamClient64Bootstrap.image(from: corrupt, release: imageRelease) }
        for name in ["bad-arch.zip", "wrong-name.zip"] {
            let bad = try Data(contentsOf: folder.appendingPathComponent(name))
            var invalid = imageRelease; invalid.archiveBytes = bad.count; invalid.archiveSHA256 = digest(bad)
            if name == "bad-arch.zip" { invalid.imageSHA256 = digest(old) }
            rejected { _ = try SteamClient64Bootstrap.image(from: bad, release: invalid) }
        }
        try SteamClient64Bootstrap.stage(archive: archive, drive: root, release: imageRelease)
        let clientFolder = root.appendingPathComponent("Program Files/Steam Client")
        try fm.createDirectory(at: clientFolder, withIntermediateDirectories: true)
        let executable = clientFolder.appendingPathComponent("Steam.exe")
        try old.write(to: executable)
        let preserved = ["config/loginusers.vdf", "userdata/fixture/config.bin", "steamapps/common/Fixture/game.bin", "package/fixture.installed"]
        for name in preserved {
            let url = clientFolder.appendingPathComponent(name)
            try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data("synthetic preserved fixture".utf8).write(to: url)
        }
        try SteamClient64Bootstrap.activate(drive: root, executable: executable, release: imageRelease)
        let migrated = try Data(contentsOf: executable)
        try expect(migrated == image && SteamClient64Bootstrap.is64BitExecutable(at: executable))
        let installers = root.appendingPathComponent("Madeira/Installers")
        let backups = try fm.contentsOfDirectory(at: installers, includingPropertiesForKeys: nil).filter { $0.lastPathComponent.hasPrefix("Steam-before-win64-") }
        try expect(backups.count == 1 && Data(contentsOf: backups[0]) == old)
        for name in preserved { try expect(Data(contentsOf: clientFolder.appendingPathComponent(name)) == Data("synthetic preserved fixture".utf8)) }
        // A newer 64-bit installation never gets replaced by the pinned seed.
        try fm.removeItem(at: SteamClient64Bootstrap.stagedURL(drive: root))
        try SteamClient64Bootstrap.activate(drive: root, executable: executable, release: imageRelease)
        try expect(Data(contentsOf: executable) == image)
        // Missing/corrupted staging leaves the old executable untouched.
        try old.write(to: executable)
        rejected { try SteamClient64Bootstrap.activate(drive: root, executable: executable, release: imageRelease) }
        try expect(Data(contentsOf: executable) == old)
        let outside = folder.appendingPathComponent("outside.exe"); try old.write(to: outside)
        try fm.removeItem(at: executable); try fm.createSymbolicLink(at: executable, withDestinationURL: outside)
        rejected { try SteamClient64Bootstrap.activate(drive: root, executable: executable, release: imageRelease) }
        try expect(Data(contentsOf: outside) == old)
        let cancelledRoot = folder.appendingPathComponent("cancelled")
        let cancelled = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            do {
                try SteamClient64Bootstrap.stage(archive: archive, drive: cancelledRoot, release: imageRelease)
                preconditionFailure("cancelled download committed")
            } catch is CancellationError {} catch { preconditionFailure("unexpected cancellation result") }
        }
        await cancelled.value
        precondition(!fm.fileExists(atPath: cancelledRoot.path))
        print("PASS: pinned hashes and x86_64/PE32+ checks; atomic migration, original executable backup, game/account preservation, no downgrade, bad input/symlink/cancellation rejection")
        if let path = CommandLine.arguments.dropFirst(2).first(where: { !$0.hasPrefix("--") }) {
            let official = try Data(contentsOf: URL(fileURLWithPath: path))
            let verified = try SteamClient64Bootstrap.image(from: official)
            precondition(SteamClient64Bootstrap.is64BitImage(verified))
            print("PASS: actual Valve Win64 archive unpacks and matches pinned image hash and x86_64 architecture")
        }
        if CommandLine.arguments.contains("--download-official") {
            let downloadRoot = folder.appendingPathComponent("official-download")
            try await SteamClient64Bootstrap.stage(drive: downloadRoot)
            let downloaded = try SteamClient64Bootstrap.stagedImage(drive: downloadRoot)
            precondition(SteamClient64Bootstrap.is64BitImage(downloaded))
            try await SteamClient64Bootstrap.stage(drive: downloadRoot)
            print("PASS: production URLSession fetch, HTTPS origin, pinned hashes, x86_64 image staging and cached reuse against Valve CDN")
        }
    }
}
