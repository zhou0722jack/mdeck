import Foundation
import CryptoKit

/// Complete matching Win32 client/CEF in its own directory. Replacing only
/// steam.exe would leave mismatched DLLs from the experimental Win64 client.
enum SteamClient32Bootstrap {
    typealias Package = SteamRuntimeFiles.Package
    static let directory = "Program Files/Steam Client32"
    static let version = "1769731672"
    // Valve steam_client_win32, checked 2026-11-13. Keep the manifest's
    // matching packages together; never mix with the moving Win64 channel.
    static let packages = [
        Package(file: "tenfoot_images_all.zip.86419c7a56c12dd107b5e0d46f50c8a9b121f3cc", bytes: 6582204, sha256: "990676bc29d01736477c6b571b5048258a6156284ef242503112fc68567cbf01"),
        Package(file: "steamui_websrc_all.zip.399ab78a41fd3867bf178d8bcee57db47a9de0bd", bytes: 30827928, sha256: "d76eabdb2eb9ceb3dd2a264ad232bdd667bdcb6d18253903ff6edbbe2f8b1f55"),
        Package(file: "resources_misc_all.zip.99ed79ed868d732d8e9e9a45444b8f003191e3dd", bytes: 4317962, sha256: "187e562403c7544af7162e08baf7677d030ad6f60947c2cdc7dcbcbf0a7a7fe6"),
        Package(file: "resources_hidpi_all.zip.a110d78e994c028dc1c412951e87a0c4e9c819f7", bytes: 98371, sha256: "5bdb97ec734f035c1d06a59b62980028b1b05b920c544ae3673b1a515d3d507e"),
        Package(file: "resources_all.zip.c0054b3a54e3b8d249a38022ccc94ba655c55eae", bytes: 3493173, sha256: "6679e6b4866758ccd33bcb9cbcbf47a1531c24e67c85a3005e97bddf1acf7c82"),
        Package(file: "strings_en_all.zip.8eef428d222948911a09e2ceb6e5e8a7225b3447", bytes: 114040, sha256: "82ccf2caa9b4f8ac58368dd273ef7a98932eec481f65e9f14080938eaa1d2d50"),
        Package(file: "strings_all.zip.4e1a9efdaf3fd4c9256366152a38a3144e60b493", bytes: 3888210, sha256: "25b9af5cf7cbc276cf3562423340923752730dfd032f1a016aa00476499ec4ab"),
        Package(file: "public_all.zip.3772dd7f589901c02941d91713a174ad2912f68e", bytes: 30703832, sha256: "54922e455d8a33785966cff838cb804dfaf99ce4a0db4dd6111c491d503ab43b"),
        Package(file: "bins_hardware_all.zip.deecd74fba6e602ef23ec442f2ddce59120e2002", bytes: 357981, sha256: "d84634553d62297f07db4d1eade0fa45757dc6e53515221bf86021520aedfbdf"),
        Package(file: "steamui_websrc_sounds_all.zip.74727ca40ef88c5012bb631488fd285418dce825", bytes: 4676203, sha256: "c823bd39d234e7d9a5fdb5ec6605eae3f175e52bb847725e8826ff526a61641c"),
        Package(file: "steamui_websrc_movies_all.zip.f556f4b9c7e087e07c0fef2da2b1d9f27f734cff", bytes: 9210097, sha256: "aa89de11cb2e8767b044d9f0aa0e37686fce03187d1c8e3eb0a70793bddb3996"),
        Package(file: "bins_codecs_win32.zip.6b4ae7fefdf9cd893140df9dc4026fbb644a3bf2", bytes: 11208316, sha256: "f2e264360d8463b238d5398796d8ad8c757a2d44f10101a8dacec856b31efa5c"),
        Package(file: "bins_misc_win32.zip.cf75dad8eda3f4e85585749c82825240e4922156", bytes: 16502790, sha256: "2c19b6407c1ea23351421642de14e6ab92024b160d05436e6e691978d4b11a78"),
        Package(file: "bins_hardware_win32.zip.5761afacd4ecada95f3b6c780bd881b46edb2f34", bytes: 7086351, sha256: "3e2687ac8fa49eaef75244316a4739e4262f2533f5e54fe0e2682807540e175b"),
        Package(file: "bins_win32.zip.23e34a6d4b10596a44561a5100dac5585d2517da", bytes: 59544006, sha256: "8b712b2a3412a9066b7725f4e1c5cef9a7ca5b187b6585a5b92d25d09df0ba62"),
        Package(file: "steam_win32.zip.3e96965d109fc2d4cc14206b2fc4ec960a746ed3", bytes: 2307664, sha256: "1369615c795b60de822876b4dc4042186cf58d0dc8f63ea1371167f667e16925"),
        Package(file: "bins_win64_win32.zip.f29d67dc38a4be027f1734802697c668621a6da1", bytes: 10509550, sha256: "345f6e4bdc19b27ae53bf752c21e2d894e0e899d94823222fb426e890d1226b5"),
        Package(file: "bins_cef_win32.zip.1c1d9dc1d899e7c8d1cff9cb0fcc11b89e412b98", bytes: 130079979, sha256: "fee14790d59463f31693ef95e10327824f5bdd95baf0aa8fae3b81aea98e794f"),
        Package(file: "bins_webhelpers_win32.zip.8a153ec2ee2090c19b25204806ffca2a7ba15bf2", bytes: 2735010, sha256: "1ab3b3834172a644759860f65d853970ba1d8b65f30190aae774395d69136307")
    ]
    static let critical = ["steam.exe", "steamclient.dll", "steamui.dll", "bin/cef/cef.win7/steamwebhelper.exe",
                           "bin/cef/cef.win7/libcef.dll", "bin/cef/cef.win7/chrome_elf.dll"]
    private static let receiptName = ".mdeck-win32.json"
    private struct Receipt: Codable { var version: String; var files: [String: String] }
    private static func invalid() -> SteamFileError {
        .invalid(L("The 32-bit Steam client could not be verified. Retry the download."))
    }
    static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
    static func is32BitImage(_ data: Data) -> Bool {
        guard data.count >= 64, data[0] == 0x4d, data[1] == 0x5a else { return false }
        let offset = (0..<4).reduce(UInt64(0)) { $0 | UInt64(data[60 + $1]) << ($1 * 8) }
        guard offset >= 64, offset <= UInt64(data.count - 26) else { return false }
        let p = Int(offset)
        return Array(data[p..<p + 4]) == [0x50, 0x45, 0, 0] && data[p + 4] == 0x4c && data[p + 5] == 0x01 &&
            data[p + 24] == 0x0b && data[p + 25] == 0x01
    }
    // Supporting x64 game DLLs are allowed; these client/UI/browser images
    // must be i386. An archive's name alone is not an architecture check.
    static func validate(folder: URL, expected: [String: String]) throws {
        guard Set(expected.keys) == Set(critical) else { throw invalid() }
        for name in critical {
            let url = try SteamRuntimeFiles.destination(name, under: folder)
            let data = try Data(contentsOf: url, options: .mappedIfSafe)
            guard is32BitImage(data), digest(data) == expected[name] else { throw invalid() }
        }
    }
    static func ready(drive: URL) -> Bool {
        guard let folder = try? SteamRuntimeFiles.destination(directory, under: drive),
              let url = try? SteamRuntimeFiles.destination(receiptName, under: folder),
              let data = try? Data(contentsOf: url), data.count < 4096,
              let receipt = try? JSONDecoder().decode(Receipt.self, from: data), receipt.version == version else { return false }
        return (try? validate(folder: folder, expected: receipt.files)) != nil
    }
    static func unpack(_ archive: Data, package: Package, into folder: URL, names: inout Set<String>, hashes: inout [String: String]) throws {
        guard archive.count == package.bytes, digest(archive) == package.sha256 else { throw invalid() }
        try SteamRuntimeFiles.unpack(archive, limits: .interactiveClient) { name, data in
            let key = name.lowercased()
            let first = key.split(separator: "/").first.map(String.init) ?? ""
            guard !["config", "userdata", "steamapps", "package"].contains(first), !first.hasPrefix("ssfn") else { throw invalid() }
            // Canonical lower-case paths match Wine's case-insensitive lookup
            // and avoid SteamUI.dll versus steamui.dll on case-sensitive hosts.
            let file = try SteamRuntimeFiles.destination(key, under: folder)
            if !names.insert(key).inserted {
                // Valve repeats resource/sourceinit.dat in two pinned
                // packages. Only an exact same-path/same-content copy is OK.
                guard digest(try Data(contentsOf: file, options: .mappedIfSafe)) == digest(data) else { throw invalid() }
                return
            }
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: file, options: .atomic)
            if critical.contains(key) { hashes[key] = digest(data) }
        }
    }
    /// Only a checked snapshot is renamed into the new directory. Unknown
    /// existing files block activation and remain untouched. No Win64 downgrade.
    static func activate(stage: URL, drive: URL, hashes: [String: String]) throws {
        try Task.checkCancellation()
        try validate(folder: stage, expected: hashes)
        let target = try SteamRuntimeFiles.destination(directory, under: drive)
        guard !FileManager.default.fileExists(atPath: target.path) else { throw SteamRuntimeFiles.Failure.conflict }
        let receipt = Receipt(version: version, files: hashes)
        try JSONEncoder().encode(receipt).write(to: stage.appendingPathComponent(receiptName), options: .atomic)
        try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Task.checkCancellation()
        try FileManager.default.moveItem(at: stage, to: target)
    }
    static func prepare(drive: URL, progress: @escaping @Sendable (Int, Int) async -> Void) async throws {
        if ready(drive: drive) { return }
        let fm = FileManager.default
        let target = try SteamRuntimeFiles.destination(directory, under: drive)
        guard !fm.fileExists(atPath: target.path) else { throw SteamRuntimeFiles.Failure.conflict }
        let stage = try SteamRuntimeFiles.destination("Madeira/Installers/Steam32-" + UUID().uuidString, under: drive)
        try fm.createDirectory(at: stage, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: stage) }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil; configuration.urlCredentialStorage = nil
        configuration.timeoutIntervalForRequest = 60; configuration.timeoutIntervalForResource = 900
        let session = URLSession(configuration: configuration, delegate: SteamRuntimeRedirects(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        var names = Set<String>(), hashes: [String: String] = [:]
        for (index, package) in packages.enumerated() {
            try Task.checkCancellation()
            await progress(index + 1, packages.count)
            let url = URL(string: SteamRuntimeFiles.origin + package.file)!
            let (download, response) = try await session.download(for: URLRequest(url: url))
            defer { try? fm.removeItem(at: download) }
            guard let response = response as? HTTPURLResponse, response.statusCode == 200,
                  response.url?.scheme == "https", response.url?.host == url.host else { throw invalid() }
            try Task.checkCancellation()
            let data = try Data(contentsOf: download, options: .mappedIfSafe)
            try unpack(data, package: package, into: stage, names: &names, hashes: &hashes)
        }
        guard wine_process_is_running() == 0, wineserver_is_running() == 0 else { throw SteamRuntimeFiles.Failure.activeSession }
        try activate(stage: stage, drive: drive, hashes: hashes)
    }
}
