import Foundation

@main struct DesktopApplicationsCheck {
    static func main() throws {
        let fm = FileManager.default
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        let prefix = root.appendingPathComponent("wine"), drive = prefix.appendingPathComponent("drive_c")
        let desktop = drive.appendingPathComponent("users/Public/Desktop")
        let userDesktop = drive.appendingPathComponent("users/madeira/Desktop")
        let programs = drive.appendingPathComponent("ProgramData/Microsoft/Windows/Start Menu/Programs")
        let userPrograms = drive.appendingPathComponent("users/madeira/AppData/Roaming/Microsoft/Windows/Start Menu/Programs")
        func write(_ data: Data, _ url: URL) throws {
            try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: url)
        }
        func exe(_ relative: String) throws { try write(Data([0x4d, 0x5a]), drive.appendingPathComponent(relative)) }
        func link(_ name: String, _ target: String, arguments: String = "") -> Data {
            DesktopApplications.shellLink(.init(name: name, target: target, arguments: arguments))
        }
        func links() throws -> [DesktopApplications.App] {
            try fm.contentsOfDirectory(at: desktop, includingPropertiesForKeys: nil).filter { $0.pathExtension == "lnk" }.compactMap {
                DesktopApplications.readLink(try Data(contentsOf: $0), name: $0.deletingPathExtension().lastPathComponent)
            }
        }
        func named(_ name: String) throws -> [DesktopApplications.App] { try links().filter { $0.name == name || $0.name.hasPrefix(name + " (") } }
        func check(_ condition: Bool, _ message: String = "desktop application fixture failed") { precondition(condition, message) }

        try exe("Program Files/Steam Client/Steam.exe")
        let steam = link("Steam", "C:\\Program Files\\Steam Client\\Steam.exe")
        try write(steam, userDesktop.appendingPathComponent("Steam.lnk"))
        try write(steam, programs.appendingPathComponent("Steam/Steam.lnk"))
        try exe("Apps/Tool.exe")
        let tool = link("Tool", "C:\\Apps\\Tool.exe", arguments: #"--project "C:\项目\项目一""#)
        try write(tool, userPrograms.appendingPathComponent("Tools/Tool.lnk"))
        try write(tool, programs.appendingPathComponent("Tool duplicate.lnk"))
        try write(link("Uninstall Tool", "C:\\Apps\\uninstall.exe"), programs.appendingPathComponent("Uninstall Tool.lnk"))
        try exe("windows/system32/notepad.exe")
        try write(link("Notepad", "C:\\windows\\system32\\notepad.exe"), programs.appendingPathComponent("Notepad.lnk"))

        for path in ["Apps/已有.exe", "Apps/注册应用.exe", "Apps/Second.exe", "Apps/Single/run.exe", "Apps/Ambiguous/a.exe",
                     "Apps/Ambiguous/b.exe", "Apps/Hidden.exe", "Games/便携游戏/运行.exe"] { try exe(path) }
        let original = link("已有应用", "C:\\Apps\\已有.exe")
        try write(original, desktop.appendingPathComponent("已有应用.lnk"))
        let registry = #"""
        WINE REGISTRY Version 2
        ;; All registry and installer source files must remain read-only.
        [Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\registered.exe]
        @="C:\\Apps\\注册应用.exe"
        [Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\registered]
        "DisplayName"="注册应用"
        "DisplayIcon"="\"C:\\Apps\\注册应用.exe\",0"
        [Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\App Paths\\second.exe]
        @="C:\\Apps\\Second.exe"
        [Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\second]
        "DisplayName"="注册应用"
        "DisplayIcon"="C:\\Apps\\Second.exe,0"
        [Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\existing]
        "DisplayName"="已有应用"
        "DisplayIcon"="C:\\Apps\\已有.exe"
        [Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\single]
        "DisplayName"="Single"
        "InstallLocation"=str(2):"C:\\Apps\\Single"
        [Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\ambiguous]
        "DisplayName"="Ambiguous"
        "InstallLocation"="C:\\Apps\\Ambiguous"
        [Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\hidden]
        "DisplayName"="Runtime component"
        "DisplayIcon"="C:\\Apps\\Hidden.exe"
        "SystemComponent"=dword:00000001
        [Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\installer]
        "DisplayName"="Only an uninstall command"
        "UninstallString"="C:\\Apps\\uninstall.exe"
        "DisplayIcon"="C:\\Apps\\not-an-executable.ico,0"
        """#
        let registryURL = prefix.appendingPathComponent("system.reg")
        try write(Data(registry.utf8), registryURL)
        let library: [String: Any] = ["version": 1, "entries": [
            ["title": "便携游戏", "relativePath": "Games/便携游戏/运行.exe", "arguments": #"--name "测试 名称""#, "workingDirectory": "C:\\Games\\便携游戏"],
            ["title": "Unsafe", "relativePath": "../outside.exe"],
            ["title": "Desktop", "relativePath": "windows/explorer.exe", "desktop": true],
            ["title": "Steam settings", "relativePath": "Program Files/Steam Client/Steam.exe", "arguments": "-console"],
            ["title": "Installer", "relativePath": "Madeira/Installers/SteamSetup.exe"]
        ]]
        try exe("Madeira/Installers/SteamSetup.exe")
        let libraryData = try JSONSerialization.data(withJSONObject: library)
        let libraryURL = root.appendingPathComponent("madeira-library.json")
        try write(libraryData, libraryURL)

        let steamApps = drive.appendingPathComponent("Program Files/Steam Client/steamapps")
        let externalApps = drive.appendingPathComponent("Games/Other Library/steamapps")
        try write(Data(#""libraryfolders" { "1" { "path" "C:\\Games\\Other Library" } }"#.utf8), steamApps.appendingPathComponent("libraryfolders.vdf"))
        func manifest(_ id: UInt32, _ name: String, _ flags: UInt32, _ root: URL) throws {
            try fm.createDirectory(at: root.appendingPathComponent("common/" + name), withIntermediateDirectories: true)
            let value = "\"AppState\" { \"appid\" \"\(id)\" \"name\" \"\(name)\" \"StateFlags\" \"\(flags)\" \"installdir\" \"\(name)\" }"
            try write(Data(value.utf8), root.appendingPathComponent("appmanifest_\(id).acf"))
        }
        try manifest(570, "Dota 2", 4, steamApps)
        try manifest(730, "下载中", 2, steamApps)
        try manifest(4242, "外部游戏", 4, externalApps)

        let singleRecord = DesktopApplications.registry(registry)["software\\microsoft\\windows\\currentversion\\uninstall\\single"]
        precondition(singleRecord?["installlocation"] == "C:\\Apps\\Single", "\(String(describing: singleRecord))")

        let first = try DesktopApplications.refresh(prefix: prefix)
        let discoveredNames = try links().map { $0.name + ":" + $0.target }
        precondition(first.added == 7 && first.removed == 0, "\(first) \(discoveredNames)")
        try check(named("Steam").isEmpty, "existing user-desktop Steam must not be duplicated")
        let copied = try Data(contentsOf: desktop.appendingPathComponent("Tool.lnk"))
        precondition(copied == tool, "Start Menu links must preserve their original bytes and arguments")
        try check(named("注册应用").count == 2, "two apps with the same display name need distinct filenames")
        try check(named("Ambiguous").isEmpty && named("Runtime component").isEmpty)
        try check(named("Notepad").isEmpty && named("Only an uninstall command").isEmpty)
        try check(named("下载中").isEmpty && named("Unsafe").isEmpty && named("Installer").isEmpty)
        try check(named("Dota 2").first?.arguments == "-applaunch 570")
        try check(named("外部游戏").first?.arguments == "-applaunch 4242")
        let portable = try named("便携游戏").first!
        precondition(portable.target == "C:\\Games\\便携游戏\\运行.exe" && portable.arguments == #"--name "测试 名称""#)
        precondition(portable.workingDirectory == "C:\\Games\\便携游戏")
        try check(Data(contentsOf: desktop.appendingPathComponent("已有应用.lnk")) == original)
        try check(Data(contentsOf: userDesktop.appendingPathComponent("Steam.lnk")) == steam)
        try check(Data(contentsOf: registryURL) == Data(registry.utf8))
        let second = try DesktopApplications.refresh(prefix: prefix)
        precondition(second.added == 0 && second.removed == 0, "refresh must be idempotent")
        print("PASS: existing desktop files, nested Start Menu, registry, Unicode, collisions, portable apps and installed Steam games")

        // Independent readers below consume these bytes, not readLink's result.
        let exported = root.appendingPathComponent("links")
        try fm.createDirectory(at: exported, withIntermediateDirectories: true)
        var expected: [[String: String]] = []
        for (index, app) in try links().enumerated() where app.shortcut != nil {
            let filename = "\(index).lnk"
            try write(app.shortcut!, exported.appendingPathComponent(filename))
            expected.append(["file": filename, "target": app.target, "arguments": app.arguments, "workingDirectory": app.workingDirectory])
        }
        try write(JSONSerialization.data(withJSONObject: expected), exported.appendingPathComponent("expected.json"))

        // Changed user shortcuts lose ownership and survive source removal.
        let modified = desktop.appendingPathComponent("Single.lnk")
        let userEdit = link("Single", "C:\\Apps\\Single\\run.exe", arguments: "--keep-my-edit")
        try write(userEdit, modified)
        try fm.removeItem(at: drive.appendingPathComponent("Apps/Single/run.exe"))
        try fm.removeItem(at: userPrograms.appendingPathComponent("Tools/Tool.lnk"))
        try fm.removeItem(at: programs.appendingPathComponent("Tool duplicate.lnk"))
        try write(Data("temporarily unreadable registry".utf8), registryURL)
        let incomplete = try DesktopApplications.refresh(prefix: prefix)
        precondition(incomplete.removed == 0 && fm.fileExists(atPath: desktop.appendingPathComponent("Tool.lnk").path))
        try write(Data(registry.utf8), registryURL)
        let afterRemoval = try DesktopApplications.refresh(prefix: prefix)
        precondition(afterRemoval.removed == 1 && !fm.fileExists(atPath: desktop.appendingPathComponent("Tool.lnk").path))
        try check(Data(contentsOf: modified) == userEdit)
        try write(Data("{".utf8), libraryURL)
        let badLibrary = try DesktopApplications.refresh(prefix: prefix)
        precondition(badLibrary.removed == 0 && fm.fileExists(atPath: desktop.appendingPathComponent("便携游戏.lnk").path))
        try write(try JSONSerialization.data(withJSONObject: ["version": 1, "entries": []]), libraryURL)
        let removedPortable = try DesktopApplications.refresh(prefix: prefix)
        precondition(removedPortable.removed == 1)
        try check(Data(contentsOf: modified) == userEdit)
        print("PASS: uninstall cleanup affects owned files only; user edits and interrupted source reads are preserved")
        for bad in [Data(), Data(repeating: 0, count: 76), steam.prefix(78), steam.prefix(120)] {
            precondition(DesktopApplications.readLink(Data(bad), name: "bad") == nil)
        }
        precondition(DesktopApplications.resolve("C:\\..\\escape.exe", drive: drive) == nil)
        precondition(DesktopApplications.resolve("D:\\outside.exe", drive: drive) == nil)
        precondition(DesktopApplications.resolve("c:\\program files\\steam client\\steam.EXE", drive: drive) != nil)
        print("PASS: malformed shortcuts, traversal and non-C-drive targets are rejected; case-insensitive files resolve")
    }
}
