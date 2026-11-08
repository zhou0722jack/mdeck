// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
import Foundation
import CryptoKit

/// Publishes launchers to the real Wine desktop. Installer-owned shortcuts,
/// registry hives and Steam manifests are read-only; only our recorded files
/// in Public/Desktop may be updated or removed.
enum DesktopApplications {
    struct App {
        var name: String
        var target: String
        var arguments = ""
        var workingDirectory = ""
        var shortcut: Data?
        var identity: String { target.lowercased() + "\n" + arguments.trimmingCharacters(in: .whitespacesAndNewlines) }
    }
    struct Receipt: Codable { var files: [String: String] = [:] }
    struct Result { var discovered = 0, added = 0, removed = 0 }
    private static let fm = FileManager.default
    private static let receiptName = ".mdeck-applications.json"
    private static let runnable = Set(["exe", "com", "bat", "cmd"])

    static func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    static func windowsPath(_ relative: String) -> String { "C:\\" + relative.replacingOccurrences(of: "/", with: "\\") }

    /// Case-insensitive lookup on the host filesystem, without accepting a
    /// Windows path that escapes the prefix. Mounted C: subdirectories work.
    static func resolve(_ path: String, drive: URL) -> URL? {
        let value = path.replacingOccurrences(of: "/", with: "\\")
        guard value.lowercased().hasPrefix("c:\\") else { return nil }
        let parts = value.dropFirst(3).split(separator: "\\").map(String.init)
        guard !parts.isEmpty, !parts.contains(where: { $0 == ".." || $0 == "." || $0.contains(":") || $0.contains("\0") }) else { return nil }
        var url = drive
        for part in parts {
            let direct = url.appendingPathComponent(part)
            if fm.fileExists(atPath: direct.path) { url = direct; continue }
            guard let names = try? fm.contentsOfDirectory(atPath: url.path),
                  let match = names.first(where: { $0.caseInsensitiveCompare(part) == .orderedSame }) else { return nil }
            url.appendPathComponent(match)
        }
        return url
    }
    private static func regular(_ url: URL) -> Bool { (try? url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true }
    private static func launchable(_ path: String, drive: URL) -> Bool {
        let name = path.replacingOccurrences(of: "\\", with: "/").lowercased()
        guard runnable.contains((name as NSString).pathExtension), !name.hasPrefix("c:/windows/"),
              !maintenance((name as NSString).lastPathComponent), let url = resolve(path, drive: drive) else { return false }
        return regular(url)
    }
    private static func maintenance(_ name: String) -> Bool {
        let value = name.lowercased()
        return value.hasPrefix("unins") || value.hasPrefix("uninstall") || value.hasPrefix("卸载")
            || value.hasPrefix("repair") || value.hasPrefix("修复")
    }
    private static func files(_ root: URL, recursive: Bool, reliable: inout Bool) -> [URL] {
        guard fm.fileExists(atPath: root.path) else { return [] }
        var failed = false
        guard let iterator = fm.enumerator(at: root, includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey],
                                          options: [.skipsHiddenFiles], errorHandler: { _, _ in failed = true; return true }) else {
            reliable = false; return []
        }
        var result: [URL] = []
        for case let url as URL in iterator {
            if iterator.level > 12 { iterator.skipDescendants(); failed = true; continue }
            if !recursive && iterator.level > 1 { iterator.skipDescendants(); continue }
            if (try? url.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) == true { iterator.skipDescendants(); continue }
            if regular(url) { result.append(url) }
            if result.count >= 8192 { failed = true; break }
        }
        if failed { reliable = false }
        return result.sorted { $0.path < $1.path }
    }
    private static func expand(_ value: String, user: String = "madeira") -> String {
        var result = value
        let variables = ["ProgramFiles": "C:\\Program Files", "ProgramFiles(x86)": "C:\\Program Files (x86)",
                         "ProgramData": "C:\\ProgramData", "SystemRoot": "C:\\windows", "windir": "C:\\windows",
                         "USERPROFILE": "C:\\users\\" + user, "PUBLIC": "C:\\users\\Public",
                         "APPDATA": "C:\\users\\" + user + "\\AppData\\Roaming",
                         "LOCALAPPDATA": "C:\\users\\" + user + "\\AppData\\Local"]
        for (key, replacement) in variables { result = result.replacingOccurrences(of: "%" + key + "%", with: replacement, options: .caseInsensitive) }
        return result
    }

    /// Shell Link header + Unicode LinkInfo and StringData. Launch arguments
    /// and working directory remain separate fields, never a shell command.
    static func shellLink(_ app: App) -> Data {
        var result = Data()
        func word(_ number: UInt32) -> Data { var n = number.littleEndian; return withUnsafeBytes(of: &n) { Data($0) } }
        func wide(_ value: String) -> Data { (value + "\0").data(using: .utf16LittleEndian)! }
        func counted(_ value: String) -> Data {
            let units = Array(value.utf16.prefix(32_000)); var n = UInt16(units.count).littleEndian
            var data = withUnsafeBytes(of: &n) { Data($0) }
            for unit in units { var u = unit.littleEndian; data.append(withUnsafeBytes(of: &u) { Data($0) }) }
            return data
        }
        result.append(word(0x4c))
        result.append(contentsOf: [1, 0x14, 2, 0, 0, 0, 0, 0, 0xc0, 0, 0, 0, 0, 0, 0, 0x46])
        result.append(word(0xb6)) // LinkInfo, Name, WorkingDir, Arguments, IsUnicode
        result.append(Data(repeating: 0, count: 4 + 24 + 4 + 4))
        result.append(word(1)); result.append(Data(repeating: 0, count: 12))
        precondition(result.count == 0x4c)
        var volume = word(17); volume.append(word(3)); volume.append(word(0)); volume.append(word(16)); volume.append(0)
        let ansi = Data(app.target.map { $0.isASCII ? UInt8($0.asciiValue!) : UInt8(63) } + [0])
        let local = 0x24 + volume.count, suffix = local + ansi.count, unicode = suffix + 1
        let target = wide(app.target), unicodeSuffix = unicode + target.count
        for n in [unicodeSuffix + 2, 0x24, 1, 0x24, local, 0, suffix, unicode, unicodeSuffix] { result.append(word(UInt32(n))) }
        result.append(volume); result.append(ansi); result.append(0); result.append(target); result.append(contentsOf: [0, 0])
        let directory = app.workingDirectory.isEmpty
            ? (app.target.replacingOccurrences(of: "\\", with: "/") as NSString).deletingLastPathComponent.replacingOccurrences(of: "/", with: "\\")
            : app.workingDirectory
        result.append(counted(app.name)); result.append(counted(directory)); result.append(counted(app.arguments))
        result.append(word(0)) // ExtraData terminal
        return result
    }

    /// Read only the fields needed to de-duplicate launchers. Unknown/PIDL-only
    /// links retain an identity based on their bytes and are still copied.
    static func readLink(_ data: Data, name: String) -> App? {
        guard data.count >= 76, u32(data, 0) == 76,
              Array(data[4..<20]) == [1, 0x14, 2, 0, 0, 0, 0, 0, 0xc0, 0, 0, 0, 0, 0, 0, 0x46],
              let flags = u32(data, 20) else { return nil }
        var offset = 76, target = "", arguments = "", working = ""
        if flags & 1 != 0 {
            guard let n = u16(data, offset), offset + 2 + Int(n) <= data.count else { return nil }
            offset += 2 + Int(n)
        }
        if flags & 2 != 0 {
            guard let n = u32(data, offset), n >= 28, offset + Int(n) <= data.count,
                  let header = u32(data, offset + 4) else { return nil }
            let end = offset + Int(n)
            if header >= 36, let at = u32(data, offset + 28), at >= header, Int(at) < Int(n) {
                target = terminated(data, offset + Int(at), end, unicode: true) ?? ""
            }
            if target.isEmpty, let at = u32(data, offset + 16), at >= header, Int(at) < Int(n) {
                target = terminated(data, offset + Int(at), end, unicode: false) ?? ""
            }
            offset = end
        }
        for flag: UInt32 in [4, 8, 16, 32, 64] where flags & flag != 0 {
            guard let count = u16(data, offset) else { return nil }
            offset += 2
            let length = Int(count) * (flags & 0x80 != 0 ? 2 : 1)
            guard offset + length <= data.count else { return nil }
            let text = String(data: data[offset..<offset + length], encoding: flags & 0x80 != 0 ? .utf16LittleEndian : .windowsCP1252) ?? ""
            if flag == 8 && target.isEmpty && text.lowercased().hasPrefix("c:\\") { target = text }
            if flag == 16 { working = text }; if flag == 32 { arguments = text }
            offset += length
        }
        return App(name: name, target: target.isEmpty ? "link:" + digest(data) : expand(target),
                   arguments: arguments, workingDirectory: working, shortcut: data)
    }
    private static func u16(_ data: Data, _ at: Int) -> UInt16? {
        guard at >= 0, at + 2 <= data.count else { return nil }
        return UInt16(data[at]) | UInt16(data[at + 1]) << 8
    }
    private static func u32(_ data: Data, _ at: Int) -> UInt32? {
        guard let a = u16(data, at), let b = u16(data, at + 2) else { return nil }; return UInt32(a) | UInt32(b) << 16
    }
    private static func terminated(_ data: Data, _ start: Int, _ end: Int, unicode: Bool) -> String? {
        var at = start
        while at + (unicode ? 1 : 0) < end {
            if data[at] == 0 && (!unicode || data[at + 1] == 0) {
                return String(data: data[start..<at], encoding: unicode ? .utf16LittleEndian : .windowsCP1252)
            }
            at += unicode ? 2 : 1
        }
        return nil
    }

    /// Wine's saved .reg format; escaped strings only, never execute registry
    /// commands or interpret UninstallString as an application launcher.
    static func registry(_ text: String) -> [String: [String: String]] {
        var records: [String: [String: String]] = [:], section: String?
        func quoted(_ value: Substring) -> String? {
            guard value.first == "\"" else { return nil }
            var out = "", escaped = false
            for c in value.dropFirst() {
                if escaped { out.append(c == "n" ? "\n" : c == "r" ? "\r" : c == "t" ? "\t" : c); escaped = false }
                else if c == "\\" { escaped = true }
                else if c == "\"" { return out }
                else { out.append(c) }
            }
            return nil
        }
        for raw in text.split(separator: "\n") {
            let line = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if line.hasPrefix("["), let end = line.firstIndex(of: "]") {
                section = String(line[line.index(after: line.startIndex)..<end]).replacingOccurrences(of: "\\\\", with: "\\").lowercased()
                continue
            }
            guard let key = section, let equal = line.firstIndex(of: "=") else { continue }
            let left = line[..<equal], right = line[line.index(after: equal)...]
            let name = left == "@" ? "" : quoted(left)?.lowercased()
            if let name {
                let value = quoted(right) ?? (right.hasPrefix("str(2):") ? quoted(right.dropFirst(7)) : nil)
                    ?? (right.hasPrefix("dword:") ? UInt32(right.dropFirst(6), radix: 16).map(String.init) : nil)
                if let value { records[key, default: [:]][name] = value }
            }
        }
        return records
    }

    static func refresh(prefix: URL) throws -> Result {
        let drive = prefix.appendingPathComponent("drive_c"), desktop = drive.appendingPathComponent("users/Public/Desktop")
        guard fm.fileExists(atPath: drive.path) else { return Result() }
        try fm.createDirectory(at: desktop, withIntermediateDirectories: true)
        let receiptURL = desktop.appendingPathComponent(receiptName)
        let previous = (try? JSONDecoder().decode(Receipt.self, from: Data(contentsOf: receiptURL))) ?? Receipt()
        var apps: [String: App] = [:], existing = Set<String>(), reliable = true
        func put(_ app: App) { if apps[app.identity] == nil { apps[app.identity] = app } }
        let users = ((try? fm.contentsOfDirectory(at: drive.appendingPathComponent("users"), includingPropertiesForKeys: nil)) ?? [])
            .filter { $0.lastPathComponent.lowercased() != "public" && $0.lastPathComponent.lowercased() != "default" }.sorted { $0.path < $1.path }
        let desktopRoots = [desktop] + users.map { $0.appendingPathComponent("Desktop") }
        func readShortcut(_ url: URL) -> App? {
            guard let data = try? Data(contentsOf: url), data.count <= 4 * 1024 * 1024 else { reliable = false; return nil }
            return readLink(data, name: url.deletingPathExtension().lastPathComponent)
        }
        // Original desktop files win and are never claimed by our receipt.
        for root in desktopRoots {
            for file in files(root, recursive: false, reliable: &reliable) where file.pathExtension.lowercased() == "lnk" {
                if root == desktop, previous.files[file.lastPathComponent] == (try? Data(contentsOf: file)).map(digest) { continue }
                if let app = readShortcut(file) { existing.insert(app.identity) }
            }
        }
        let programs = users.map { $0.appendingPathComponent("AppData/Roaming/Microsoft/Windows/Start Menu/Programs") }
            + [drive.appendingPathComponent("ProgramData/Microsoft/Windows/Start Menu/Programs")]
        for root in programs {
            for file in files(root, recursive: true, reliable: &reliable) where file.pathExtension.lowercased() == "lnk" && !maintenance(file.lastPathComponent) {
                guard let app = readShortcut(file) else { reliable = false; continue }
                if app.target.hasPrefix("link:") || launchable(app.target, drive: drive) { put(app) }
            }
        }
        var records: [String: [String: String]] = [:]
        for name in ["system.reg", "user.reg"] {
            let file = prefix.appendingPathComponent(name)
            guard fm.fileExists(atPath: file.path) else { continue }
            guard let text = try? String(contentsOf: file, encoding: .utf8), text.hasPrefix("WINE REGISTRY Version") else { reliable = false; continue }
            records.merge(registry(text), uniquingKeysWith: { a, b in a.merging(b, uniquingKeysWith: { _, new in new }) })
        }
        func executable(_ text: String) -> String {
            let value = expand(text.trimmingCharacters(in: .whitespacesAndNewlines))
            if value.hasPrefix("\""), let end = value.dropFirst().firstIndex(of: "\"") { return String(value[value.index(after: value.startIndex)..<end]) }
            return value.split(separator: ",", maxSplits: 1).first.map(String.init) ?? value
        }
        let uninstall = records.filter { $0.key.contains("\\currentversion\\uninstall\\") }
        var titles: [String: String] = [:]
        for (_, values) in uninstall {
            if let name = values["displayname"], let icon = values["displayicon"] { titles[executable(icon).lowercased()] = name }
        }
        for (key, values) in records.sorted(by: { $0.key < $1.key }) where key.contains("\\currentversion\\app paths\\") {
            if let value = values[""] {
                let target = executable(value)
                if launchable(target, drive: drive) {
                    put(App(name: titles[target.lowercased()] ?? ((target.replacingOccurrences(of: "\\", with: "/") as NSString).lastPathComponent as NSString).deletingPathExtension,
                            target: target))
                }
            }
        }
        for (_, values) in uninstall.sorted(by: { $0.key < $1.key }) {
            guard let name = values["displayname"], !maintenance(name), values["systemcomponent"] != "1" else { continue }
            if let icon = values["displayicon"] {
                let target = executable(icon)
                if launchable(target, drive: drive) { put(App(name: name, target: target)); continue }
            }
            // Missing shortcuts: accept only an unambiguous executable in the
            // registered installation directory; never choose a random helper.
            if let location = values["installlocation"], let folder = resolve(expand(location), drive: drive) {
                let base = expand(location).replacingOccurrences(of: "/", with: "\\").trimmingCharacters(in: CharacterSet(charactersIn: "\\"))
                func target(_ file: URL) -> String { base + "\\" + file.lastPathComponent }
                let candidates = files(folder, recursive: false, reliable: &reliable).filter {
                    launchable(target($0), drive: drive)
                }
                let exact = candidates.filter { $0.deletingPathExtension().lastPathComponent.caseInsensitiveCompare(name) == .orderedSame }
                if let file = exact.first ?? (candidates.count == 1 ? candidates.first : nil) {
                    put(App(name: name, target: target(file)))
                }
            }
        }
        // The native downloader writes standard manifests, not Start Menu
        // links. Publish installed games as Steam app-id launches, not guessed EXEs.
        let steamPath = "C:\\Program Files\\Steam Client\\Steam.exe"
        if launchable(steamPath, drive: drive) {
            put(App(name: "Steam", target: steamPath))
            var steamApps = [drive.appendingPathComponent("Program Files/Steam Client/steamapps"), drive.appendingPathComponent("Program Files (x86)/Steam/steamapps")]
            for root in steamApps {
                let vdf = root.appendingPathComponent("libraryfolders.vdf")
                if let data = try? Data(contentsOf: vdf), var parser = try? SteamKeyValues(data), let value = try? parser.read() {
                    for node in value["libraryfolders"]?.fields.values ?? [:].values {
                        if let path = node["path"]?.string, let folder = resolve(path + "\\steamapps", drive: drive) { steamApps.append(folder) }
                    }
                } else if fm.fileExists(atPath: vdf.path) { reliable = false }
            }
            var seenRoots = Set<String>()
            for root in steamApps where seenRoots.insert(root.standardizedFileURL.path).inserted {
                for file in files(root, recursive: false, reliable: &reliable) where file.lastPathComponent.hasPrefix("appmanifest_") && file.pathExtension == "acf" {
                    guard let data = try? Data(contentsOf: file), var parser = try? SteamKeyValues(data), let value = try? parser.read(),
                          let app = value["appstate"], let id = app["appid"]?.string, let number = UInt32(id), number > 0,
                          let flags = UInt32(app["stateflags"]?.string ?? ""),
                          let name = app["name"]?.string, let directory = app["installdir"]?.string else { reliable = false; continue }
                    guard flags & 4 != 0, !directory.isEmpty,
                          !directory.contains("/"), !directory.contains("\\"), directory != "..", directory != ".",
                          fm.fileExists(atPath: root.appendingPathComponent("common").appendingPathComponent(directory).path) else { continue }
                    put(App(name: name, target: steamPath, arguments: "-applaunch \(number)"))
                }
            }
        }
        let libraryFile = prefix.deletingLastPathComponent().appendingPathComponent("madeira-library.json")
        if let data = try? Data(contentsOf: libraryFile),
           data.count <= 32 * 1024 * 1024,
           let document = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
           document["version"] as? Int == 1, let entries = document["entries"] as? [[String: Any]] {
            for entry in entries {
                guard entry["desktop"] as? Bool != true, entry["steamAppID"] == nil,
                      let name = entry["title"] as? String, let relative = entry["relativePath"] as? String,
                      !relative.lowercased().hasPrefix("madeira/installers/"),
                      relative.lowercased() != "program files/steam client/steam.exe" else { continue }
                let target = windowsPath(relative)
                if launchable(target, drive: drive) {
                    put(App(name: name, target: target, arguments: entry["arguments"] as? String ?? "",
                            workingDirectory: entry["workingDirectory"] as? String ?? ""))
                }
            }
        } else if fm.fileExists(atPath: libraryFile.path) { reliable = false }
        var receipt = Receipt(), result = Result(); result.discovered = apps.count
        var occupied = Set(((try? fm.contentsOfDirectory(atPath: desktop.path)) ?? []).map { $0.lowercased() })
        for app in apps.values.sorted(by: { $0.name == $1.name ? $0.identity < $1.identity : $0.name < $1.name }) where !existing.contains(app.identity) {
            let payload = app.shortcut ?? shellLink(app), hash = digest(payload)
            let safe = String(app.name.map { "\\/:*?\"<>|\0".contains($0) || $0.isNewline ? "_" : $0 }.prefix(100)).trimmingCharacters(in: .whitespacesAndNewlines)
            let stem = safe.isEmpty ? "Application" : safe
            var name = stem + ".lnk", suffix = 2
            while occupied.contains(name.lowercased()) {
                let file = desktop.appendingPathComponent(name)
                if receipt.files[name] == nil, previous.files[name] == (try? Data(contentsOf: file)).map(digest) { break }
                name = stem + " (\(suffix)).lnk"; suffix += 1
            }
            let file = desktop.appendingPathComponent(name)
            if (try? Data(contentsOf: file)) != payload { try payload.write(to: file, options: .atomic); result.added += 1 }
            receipt.files[name] = hash; occupied.insert(name.lowercased())
        }
        if reliable {
            for (name, hash) in previous.files where receipt.files[name] == nil && name == (name as NSString).lastPathComponent && name.hasSuffix(".lnk") {
                let file = desktop.appendingPathComponent(name)
                if let data = try? Data(contentsOf: file), digest(data) == hash { try fm.removeItem(at: file); result.removed += 1 }
            }
        } else {
            for (name, hash) in previous.files where receipt.files[name] == nil { receipt.files[name] = hash }
        }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(receipt)
        if (try? Data(contentsOf: receiptURL)) != data { try data.write(to: receiptURL, options: .atomic) }
        return result
    }
}

#if canImport(UIKit)
import UIKit

private enum DesktopApplicationMonitor {
    static let queue = DispatchQueue(label: "mdeck.desktop-applications", qos: .utility)
    static var timer: DispatchSourceTimer?
    static func sync(_ prefix: URL) {
        do {
            let result = try DesktopApplications.refresh(prefix: prefix)
            if result.added > 0 || result.removed > 0 {
                LogStore.shared.log("[desktop-apps] discovered=\(result.discovered) updated=\(result.added) removed=\(result.removed)")
            }
        } catch { LogStore.shared.log("[desktop-apps] shortcut sync failed: \(error.localizedDescription)") }
    }
}

@_cdecl("madeira_prepare_desktop_applications")
func madeiraPrepareDesktopApplications(_ path: UnsafePointer<CChar>?) {
    guard let path else { return }
    let prefix = URL(fileURLWithPath: String(cString: path))
    DesktopApplicationMonitor.queue.sync {
        DesktopApplicationMonitor.timer?.cancel()
        DesktopApplicationMonitor.sync(prefix)
        let timer = DispatchSource.makeTimerSource(queue: DesktopApplicationMonitor.queue)
        timer.schedule(deadline: .now() + 10, repeating: 15)
        timer.setEventHandler {
            DispatchQueue.main.async {
                guard UIApplication.shared.applicationState == .active,
                      wine_process_is_running() != 0 || wineserver_is_running() != 0 else { return }
                DesktopApplicationMonitor.queue.async { DesktopApplicationMonitor.sync(prefix) }
            }
        }
        DesktopApplicationMonitor.timer = timer
        timer.resume()
    }
}
#endif
