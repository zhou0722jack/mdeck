// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import CryptoKit
import Darwin

/// Runs before Wine starts the installed Win64 web helper. All large-file IO
/// is streamed. A durable journal recovers an interrupted two-file replacement.
enum SteamCEFPoolPatch {
    struct EditGroup: Decodable {
        var before: Data
        var after: Data
        var offsets: [UInt64]
    }
    struct Patch: Decodable {
        var name: String
        var sourceSHA256: String
        var outputSHA256: String
        var sourceSize: UInt64
        var outputSize: UInt64
        var groups: [EditGroup]
    }
    struct Package: Decodable {
        var version: Int
        var patches: [Patch]
    }
    private struct Journal: Codable {
        var version: Int
        var previous: [String: String]
    }
    enum Outcome: String { case applied, alreadyApplied, unsupportedVersion }
    enum Failure: Error { case invalidResource, changedFile, invalidBackup, io(Int32) }
    private struct FileIdentity: Equatable {
        var device: Int32
        var inode: UInt64
        var size: Int64
        var modifiedSeconds: Int
        var modifiedNanoseconds: Int
        var changedSeconds: Int
        var changedNanoseconds: Int

        init(_ file: URL) throws {
            var value = stat()
            guard lstat(file.path, &value) == 0 else { throw Failure.io(errno) }
            guard value.st_mode & S_IFMT == S_IFREG else { throw Failure.changedFile }
            device = value.st_dev
            inode = value.st_ino
            size = value.st_size
            modifiedSeconds = value.st_mtimespec.tv_sec
            modifiedNanoseconds = value.st_mtimespec.tv_nsec
            changedSeconds = value.st_ctimespec.tv_sec
            changedNanoseconds = value.st_ctimespec.tv_nsec
        }
    }
    private final class VerificationCache: @unchecked Sendable {
        let lock = NSLock()
        var folder: String?
        var files: [FileIdentity]?
    }
    private static let verification = VerificationCache()
    private static let names = ["libcef.dll", "chrome_elf.dll"]

    static func digest(_ file: URL) throws -> String {
        let input = try FileHandle(forReadingFrom: file)
        defer { try? input.close() }
        var hash = SHA256()
        while let bytes = try input.read(upToCount: 1024 * 1024), !bytes.isEmpty {
            hash.update(data: bytes)
        }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private static func regular(_ file: URL) throws {
        let values = try file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true else { throw Failure.changedFile }
    }

    /// Match actual case on a case-sensitive host and refuse ambiguous aliases.
    private static func child(_ name: String, in folder: URL) throws -> URL {
        let matches = try FileManager.default.contentsOfDirectory(atPath: folder.path)
            .filter { $0.caseInsensitiveCompare(name) == .orderedSame }
        guard matches.count == 1 else { throw Failure.changedFile }
        let result = folder.appendingPathComponent(matches[0])
        try regular(result)
        return result
    }

    private static func syncFile(_ file: URL) throws {
        let handle = try FileHandle(forWritingTo: file)
        defer { try? handle.close() }
        try handle.synchronize()
    }

    private static func syncDirectory(_ directory: URL) throws {
        let fd = open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
        guard fd >= 0 else { throw Failure.io(errno) }
        defer { close(fd) }
        guard fsync(fd) == 0 else { throw Failure.io(errno) }
    }

    private static func move(_ source: URL, over target: URL) throws {
        guard rename(source.path, target.path) == 0 else { throw Failure.io(errno) }
        try syncDirectory(target.deletingLastPathComponent())
    }

    private static func copy(_ source: URL, to target: URL) throws {
        let fm = FileManager.default
        if fm.fileExists(atPath: target.path) { try fm.removeItem(at: target) }
        try fm.copyItem(at: source, to: target)
        try syncFile(target)
    }

    private static func backup(_ patch: Patch, hash: String, in work: URL) -> URL {
        work.appendingPathComponent(patch.name + "." + hash + ".original")
    }

    private static func recover(_ journalURL: URL, work: URL, files: [String: URL], package: Package) throws {
        let fm = FileManager.default
        guard fm.fileExists(atPath: journalURL.path) else { return }
        try regular(journalURL)
        let journal = try JSONDecoder().decode(Journal.self, from: Data(contentsOf: journalURL))
        guard journal.version == 1, Set(journal.previous.keys) == Set(names) else { throw Failure.invalidBackup }
        // Validate both backups and current destinations before any recovery write.
        for patch in package.patches {
            guard let hash = journal.previous[patch.name],
                  [patch.sourceSHA256, patch.outputSHA256].contains(hash) else { throw Failure.invalidBackup }
            let saved = backup(patch, hash: hash, in: work)
            try regular(saved)
            guard try digest(saved) == hash else { throw Failure.invalidBackup }
            let current = try digest(files[patch.name]!)
            guard [hash, patch.outputSHA256].contains(current) else { throw Failure.changedFile }
        }
        for patch in package.patches {
            let saved = backup(patch, hash: journal.previous[patch.name]!, in: work)
            let rollback = work.appendingPathComponent(patch.name + ".rollback")
            try copy(saved, to: rollback)
            try move(rollback, over: files[patch.name]!)
        }
        try fm.removeItem(at: journalURL)
        try syncDirectory(work)
    }

    private static func stage(_ patch: Patch, source: URL, output: URL) throws {
        try copy(source, to: output)
        let handle = try FileHandle(forUpdating: output)
        defer { try? handle.close() }
        for group in patch.groups {
            guard !group.before.isEmpty, group.before.count == group.after.count else { throw Failure.invalidResource }
            for offset in group.offsets {
                guard UInt64(group.before.count) <= patch.outputSize,
                      offset <= patch.outputSize - UInt64(group.before.count) else { throw Failure.invalidResource }
                try handle.seek(toOffset: offset)
                guard try handle.read(upToCount: group.before.count) == group.before else { throw Failure.changedFile }
                try handle.seek(toOffset: offset)
                try handle.write(contentsOf: group.after)
            }
        }
        try handle.truncate(atOffset: patch.outputSize)
        try handle.synchronize()
        guard try digest(output) == patch.outputSHA256 else { throw Failure.invalidResource }
    }

    /// afterReplace is a fault-injection seam for crash recovery tests.
    static func apply(in folder: URL, resource: URL, afterReplace: ((Int) throws -> Void)? = nil) throws -> Outcome {
        verification.lock.lock()
        defer { verification.lock.unlock() }
        let package = try JSONDecoder().decode(Package.self, from: Data(contentsOf: resource))
        guard package.version == 1, package.patches.map(\.name) == names,
              package.patches.allSatisfy({ $0.outputSize > 0 && $0.outputSize <= $0.sourceSize }) else {
            throw Failure.invalidResource
        }
        let fm = FileManager.default
        let files = try Dictionary(uniqueKeysWithValues: names.map { ($0, try child($0, in: folder)) })
        let work = folder.appendingPathComponent(".mdeck-cef-4gib", isDirectory: true)
        try fm.createDirectory(at: work, withIntermediateDirectories: true)
        let values = try work.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        guard values.isDirectory == true, values.isSymbolicLink != true else { throw Failure.invalidBackup }
        let fd = open(work.appendingPathComponent("lock").path, O_CREAT | O_RDWR | O_NOFOLLOW, 0o600)
        guard fd >= 0 else { throw Failure.io(errno) }
        defer { flock(fd, LOCK_UN); close(fd) }
        guard flock(fd, LOCK_EX) == 0 else { throw Failure.io(errno) }
        let journalURL = work.appendingPathComponent("transaction.json")
        if fm.fileExists(atPath: journalURL.path) { verification.files = nil }
        try recover(journalURL, work: work, files: files, package: package)
        let identities = try (names.map { files[$0]! } + [resource]).map(FileIdentity.init)
        if verification.folder == folder.path, verification.files == identities { return .alreadyApplied }
        verification.files = nil
        var hashes: [String: String] = [:]
        for patch in package.patches { hashes[patch.name] = try digest(files[patch.name]!) }
        guard try (names.map { files[$0]! } + [resource]).map(FileIdentity.init) == identities else {
            throw Failure.changedFile
        }
        guard package.patches.allSatisfy({ [ $0.sourceSHA256, $0.outputSHA256 ].contains(hashes[$0.name]!) }) else {
            return .unsupportedVersion
        }
        if package.patches.allSatisfy({ hashes[$0.name] == $0.outputSHA256 }) {
            verification.folder = folder.path
            verification.files = identities
            return .alreadyApplied
        }
        for patch in package.patches {
            let file = files[patch.name]!, hash = hashes[patch.name]!
            let saved = backup(patch, hash: hash, in: work)
            if !fm.fileExists(atPath: saved.path) {
                let temporary = work.appendingPathComponent(patch.name + ".backup.tmp")
                try copy(file, to: temporary)
                guard try digest(temporary) == hash else { throw Failure.changedFile }
                try move(temporary, over: saved)
            }
            try regular(saved)
            guard try digest(saved) == hash else { throw Failure.invalidBackup }
            let staged = work.appendingPathComponent(patch.name + ".ready")
            if hash == patch.outputSHA256 { try copy(file, to: staged) }
            else { try stage(patch, source: file, output: staged) }
        }
        for patch in package.patches {
            guard try digest(files[patch.name]!) == hashes[patch.name] else { throw Failure.changedFile }
        }
        try JSONEncoder().encode(Journal(version: 1, previous: hashes)).write(to: journalURL, options: .atomic)
        try syncFile(journalURL)
        try syncDirectory(work)
        do {
            for (index, patch) in package.patches.enumerated() {
                let file = files[patch.name]!
                guard try digest(file) == hashes[patch.name] else { throw Failure.changedFile }
                try move(work.appendingPathComponent(patch.name + ".ready"), over: file)
                try afterReplace?(index)
            }
            let verified = try (names.map { files[$0]! } + [resource]).map(FileIdentity.init)
            for patch in package.patches {
                guard try digest(files[patch.name]!) == patch.outputSHA256 else { throw Failure.changedFile }
            }
            guard try (names.map { files[$0]! } + [resource]).map(FileIdentity.init) == verified else {
                throw Failure.changedFile
            }
            try fm.removeItem(at: journalURL)
            try syncDirectory(work)
            // Each CEF child reuses this verification only while both DLLs and
            // the bundled recipe retain the identity checked around hashing.
            verification.folder = folder.path
            verification.files = verified
        } catch {
            try recover(journalURL, work: work, files: files, package: package)
            throw error
        }
        return .applied
    }

    /// unixName comes from Wine's resolved PE path, before child creation.
    static func prepare(helper: URL, drive: URL, resource: URL) throws -> Outcome? {
        let expected = drive.appendingPathComponent("Program Files/Steam Client/bin/cef/cef.win64/steamwebhelper.exe")
        guard helper.resolvingSymlinksInPath().path.caseInsensitiveCompare(expected.resolvingSymlinksInPath().path) == .orderedSame,
              try SteamClient64Bootstrap.is64BitExecutable(at: helper) else { return nil }
        return try apply(in: helper.deletingLastPathComponent(), resource: resource)
    }
}

@_cdecl("madeira_steam_cef_prepare")
func madeiraSteamCEFPrepare(_ unixName: UnsafePointer<CChar>?) -> Int32 {
    guard let unixName, let prefix = getenv("WINEPREFIX") else { return 0 }
    let helper = URL(fileURLWithPath: String(cString: unixName)).resolvingSymlinksInPath()
    let drive = URL(fileURLWithPath: String(cString: prefix)).appendingPathComponent("drive_c").resolvingSymlinksInPath()
    let expected = drive.appendingPathComponent("Program Files/Steam Client/bin/cef/cef.win64/steamwebhelper.exe")
    guard helper.path.caseInsensitiveCompare(expected.path) == .orderedSame else { return 0 }
    do {
        guard let resource = Bundle.main.url(forResource: "SteamCEF4GiB", withExtension: "json", subdirectory: "BundledInstallers") else {
            throw SteamCEFPoolPatch.Failure.invalidResource
        }
        if let result = try SteamCEFPoolPatch.prepare(helper: helper, drive: drive, resource: resource) {
            if result == .unsupportedVersion {
                fputs("[steam-cef-patch] unsupported CEF version; keeping installed DLLs\n", stderr)
            } else {
                fputs("[steam-cef-patch] \(result.rawValue); paired Win64 CEF 4 GiB pools\n", stderr)
            }
        }
        return 0
    } catch {
        fputs("[steam-cef-patch] replacement failed; web helper start stopped: \(error)\n", stderr)
        return -1
    }
}
