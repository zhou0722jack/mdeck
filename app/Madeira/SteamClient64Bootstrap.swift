import Foundation
import CryptoKit

/// Valve's Win64 bootstrapper prepares its matching client/CEF packages.
/// Only this image is migrated here; account and game files stay in place.
enum SteamClient64Bootstrap {
    struct Release {
        var file: String
        var archiveBytes: Int
        var archiveSHA256: String
        var imageBytes: Int
        var imageSHA256: String
    }
    // Valve steam_client_win64, version 1792618285, checked 2026-11-08.
    static let current = Release(
        file: "steam_win64.zip.9ddc7f402ba9bec08b7dbee2cf6ee37d21e1b4e0", archiveBytes: 2_692_595,
        archiveSHA256: "9a5aba7f8b5341344717f4a07027ac128e6913bb918454672e843fb5f7e61468",
        imageBytes: 5_823_128, imageSHA256: "f8a4ca44008c516eebecafaa4bc26772b2a6eb0fef8034bce56a3311e21ab705")
    static let origin = "https://client-update.akamai.steamstatic.com/"
    static let stagedPath = "Madeira/Installers/Steam64.exe"

    private static func invalid() -> SteamFileError {
        .invalid(L("The 64-bit Steam client could not be verified. Retry the download."))
    }
    static func is64BitImage(_ data: Data) -> Bool {
        guard data.count >= 64, data[0] == 0x4d, data[1] == 0x5a else { return false }
        let offset = (0..<4).reduce(UInt64(0)) { $0 | UInt64(data[60 + $1]) << ($1 * 8) }
        guard offset >= 64, offset <= UInt64(data.count - 26) else { return false }
        let pe = Int(offset)
        return Array(data[pe..<pe + 4]) == [0x50, 0x45, 0, 0] &&
            data[pe + 4] == 0x64 && data[pe + 5] == 0x86 && data[pe + 24] == 0x0b && data[pe + 25] == 0x02
    }
    static func is64BitExecutable(at url: URL) throws -> Bool {
        let handle = try FileHandle(forReadingFrom: url); defer { try? handle.close() }
        let dos = try handle.read(upToCount: 64) ?? Data()
        guard dos.count == 64, dos[0] == 0x4d, dos[1] == 0x5a else { return false }
        let offset = (0..<4).reduce(UInt64(0)) { $0 | UInt64(dos[60 + $1]) << ($1 * 8) }
        guard offset >= 64, offset < 16 * 1024 * 1024 else { return false }
        try handle.seek(toOffset: offset)
        let pe = try handle.read(upToCount: 26) ?? Data()
        return pe.count == 26 && Array(pe.prefix(4)) == [0x50, 0x45, 0, 0] &&
            pe[4] == 0x64 && pe[5] == 0x86 && pe[24] == 0x0b && pe[25] == 0x02
    }
    static func validateImage(_ data: Data, release: Release = current) throws {
        guard data.count == release.imageBytes, is64BitImage(data),
              SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == release.imageSHA256 else { throw invalid() }
    }
    static func image(from archive: Data, release: Release = current) throws -> Data {
        guard archive.count == release.archiveBytes,
              SHA256.hash(data: archive).map({ String(format: "%02x", $0) }).joined() == release.archiveSHA256 else { throw invalid() }
        var image: Data?
        try SteamRuntimeFiles.unpack(archive) { name, data in
            guard name.caseInsensitiveCompare("steam.exe") == .orderedSame, image == nil else { throw invalid() }
            image = data
        }
        guard let image else { throw invalid() }
        try validateImage(image, release: release)
        return image
    }
    static func stagedURL(drive: URL) throws -> URL {
        try SteamRuntimeFiles.destination(stagedPath, under: drive)
    }
    static func stagedImage(drive: URL, release: Release = current) throws -> Data {
        let url = try stagedURL(drive: drive)
        guard try url.resourceValues(forKeys: [.fileSizeKey]).fileSize == release.imageBytes else { throw invalid() }
        let data = try Data(contentsOf: url)
        try validateImage(data, release: release)
        return data
    }
    static func stage(drive: URL) async throws {
        try Task.checkCancellation()
        if (try? stagedImage(drive: drive)) != nil { return }
        var request = URLRequest(url: URL(string: origin + current.file)!, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 60)
        request.setValue("mdeck", forHTTPHeaderField: "User-Agent")
        let (archive, response) = try await URLSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse, response.statusCode == 200,
              response.url?.scheme == "https", response.url?.host == "client-update.akamai.steamstatic.com" else { throw invalid() }
        try Task.checkCancellation()
        try stage(archive: archive, drive: drive)
    }
    static func stage(archive: Data, drive: URL, release: Release = current) throws {
        let data = try image(from: archive, release: release)
        try Task.checkCancellation()
        let target = try stagedURL(drive: drive)
        try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: target, options: .atomic)
    }
    /// Existing installs: back up the old executable, then atomically replace
    /// only that image. No config/userdata/steamapps/package deletion.
    static func activate(drive: URL, executable: URL, release: Release = current) throws {
        let fm = FileManager.default
        let folder = try SteamRuntimeFiles.destination("Program Files/Steam Client", under: drive)
        let values = try executable.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
        guard executable.deletingLastPathComponent().standardizedFileURL.path == folder.standardizedFileURL.path,
              executable.lastPathComponent.caseInsensitiveCompare("steam.exe") == .orderedSame,
              values.isRegularFile == true, values.isSymbolicLink != true else { throw invalid() }
        if try is64BitExecutable(at: executable) { return }
        let data = try stagedImage(drive: drive, release: release)
        try Task.checkCancellation()
        let backup = try SteamRuntimeFiles.destination("Madeira/Installers/Steam-before-win64-" + UUID().uuidString + ".exe", under: drive)
        try fm.copyItem(at: executable, to: backup)
        try data.write(to: executable, options: .atomic)
        guard try is64BitExecutable(at: executable) else { throw invalid() }
    }
}
