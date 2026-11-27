import Foundation
import Darwin

func wine_process_is_running() -> Int32 { 0 }
func wineserver_is_running() -> Int32 { 0 }
func madeira_seed_prefix_if_needed(_ path: String) {}

@main struct Check {
    enum Injected: Error { case stop }
    static func main() throws {
        let args = CommandLine.arguments
        let action = args[1], root = URL(fileURLWithPath: args[2]).resolvingSymlinksInPath()
        let originals = URL(fileURLWithPath: args[3])
        let resource = URL(fileURLWithPath: args[4])
        let helperSource = URL(fileURLWithPath: args[5])
        let drive = root.appendingPathComponent("drive_c")
        let folder = drive.appendingPathComponent("Program Files/Steam Client/bin/cef/cef.win64")
        let helper = folder.appendingPathComponent("steamwebhelper.exe")
        let fm = FileManager.default
        let package = try JSONDecoder().decode(SteamCEFPoolPatch.Package.self, from: Data(contentsOf: resource))
        func reset() throws {
            if fm.fileExists(atPath: root.path) { try fm.removeItem(at: root) }
            try fm.createDirectory(at: folder, withIntermediateDirectories: true)
            for patch in package.patches {
                try fm.copyItem(at: originals.appendingPathComponent(patch.name), to: folder.appendingPathComponent(patch.name))
            }
            try fm.copyItem(at: helperSource, to: helper)
        }
        func expect(_ condition: @autoclosure () throws -> Bool) throws {
            let value = try condition()
            precondition(value)
        }
        func originalPair() throws {
            for patch in package.patches {
                try expect(SteamCEFPoolPatch.digest(folder.appendingPathComponent(patch.name)) == patch.sourceSHA256)
            }
        }
        func patchedPair() throws {
            for patch in package.patches {
                try expect(SteamCEFPoolPatch.digest(folder.appendingPathComponent(patch.name)) == patch.outputSHA256)
                let backup = folder.appendingPathComponent(".mdeck-cef-4gib/" + patch.name + "." + patch.sourceSHA256 + ".original")
                try expect(SteamCEFPoolPatch.digest(backup) == patch.sourceSHA256)
            }
        }
        switch action {
        case "concurrent-setup":
            try reset()
        case "prepare":
            let outcome = try SteamCEFPoolPatch.prepare(helper: helper, drive: drive, resource: resource)
            try expect(outcome == .applied || outcome == .alreadyApplied)
            try patchedPair()
            print("PASS: concurrent process uses one consistent verified pair")
        case "partial-update":
            try reset()
            _ = try SteamCEFPoolPatch.prepare(helper: helper, drive: drive, resource: resource)
            let first = package.patches[0]
            try fm.removeItem(at: folder.appendingPathComponent(first.name))
            try fm.copyItem(at: originals.appendingPathComponent(first.name), to: folder.appendingPathComponent(first.name))
            try expect(SteamCEFPoolPatch.prepare(helper: helper, drive: drive, resource: resource) == .applied)
            try patchedPair()
            print("PASS: updater restoring only one original invalidates cached verification and repairs the pair")
        case "cache":
            try reset()
            _ = try SteamCEFPoolPatch.prepare(helper: helper, drive: drive, resource: resource)
            let file = folder.appendingPathComponent("libcef.dll")
            let handle = try FileHandle(forUpdating: file)
            try handle.seek(toOffset: 1024)
            try handle.write(contentsOf: Data([0x19, 0x29, 0x39, 0x49]))
            try handle.close()
            try expect(SteamCEFPoolPatch.prepare(helper: helper, drive: drive, resource: resource) == .unsupportedVersion)
            print("PASS: same-size in-place DLL change invalidates cached verification")
        case "normal":
            try reset()
            try expect(SteamCEFPoolPatch.prepare(helper: helper, drive: drive, resource: resource) == .applied)
            try patchedPair()
            try expect(SteamCEFPoolPatch.prepare(helper: helper, drive: drive, resource: resource) == .alreadyApplied)
            // A real updater may restore both original files before the next helper start.
            for patch in package.patches {
                try fm.removeItem(at: folder.appendingPathComponent(patch.name))
                try fm.copyItem(at: originals.appendingPathComponent(patch.name), to: folder.appendingPathComponent(patch.name))
            }
            try expect(SteamCEFPoolPatch.prepare(helper: helper, drive: drive, resource: resource) == .applied)
            try patchedPair()
            print("PASS: paired DLLs reproduce verified hashes, keep originals, repeat safely, reapply after updater replacement")
        case "rollback":
            try reset()
            do {
                _ = try SteamCEFPoolPatch.apply(in: folder, resource: resource) { index in
                    if index == 0 { throw Injected.stop }
                }
                preconditionFailure("injected failure ignored")
            } catch Injected.stop {}
            try originalPair()
            try expect(!fm.fileExists(atPath: folder.appendingPathComponent(".mdeck-cef-4gib/transaction.json").path))
            print("PASS: failure after first replacement restores both originals")
        case "crash":
            try reset()
            _ = try SteamCEFPoolPatch.apply(in: folder, resource: resource) { index in
                if index == 0 { _exit(77) }
            }
            preconditionFailure("crash not injected")
        case "recover":
            try expect(fm.fileExists(atPath: folder.appendingPathComponent(".mdeck-cef-4gib/transaction.json").path))
            try expect(SteamCEFPoolPatch.prepare(helper: helper, drive: drive, resource: resource) == .applied)
            try patchedPair()
            print("PASS: new OS process recovers a half-replaced pair after abrupt exit, then installs both verified DLLs")
        case "unknown":
            try reset()
            let file = folder.appendingPathComponent("libcef.dll")
            let handle = try FileHandle(forUpdating: file)
            try handle.seek(toOffset: 1024)
            try handle.write(contentsOf: Data([0x19, 0x29, 0x39, 0x49]))
            try handle.close()
            let unknown = try SteamCEFPoolPatch.digest(file)
            try expect(SteamCEFPoolPatch.prepare(helper: helper, drive: drive, resource: resource) == .unsupportedVersion)
            try expect(SteamCEFPoolPatch.digest(file) == unknown)
            try expect(SteamCEFPoolPatch.digest(folder.appendingPathComponent("chrome_elf.dll")) == package.patches[1].sourceSHA256)
            print("PASS: unknown Steam/CEF version preserves both installed DLLs")
        case "scope":
            try reset()
            let otherDrive = root.appendingPathComponent("another-drive")
            try expect(SteamCEFPoolPatch.prepare(helper: helper, drive: otherDrive, resource: resource) == nil)
            var pe = Data(repeating: 0, count: 512)
            pe[0] = 0x4d; pe[1] = 0x5a; pe[60] = 128
            pe.replaceSubrange(128..<134, with: [0x50, 0x45, 0, 0, 0x4c, 0x01])
            pe[152] = 0x0b; pe[153] = 0x01
            try pe.write(to: helper)
            try expect(SteamCEFPoolPatch.prepare(helper: helper, drive: drive, resource: resource) == nil)
            try originalPair()
            print("PASS: unrelated install and 32-bit web helper excluded")
        case "bad-backup":
            try reset()
            let work = folder.appendingPathComponent(".mdeck-cef-4gib")
            try fm.createDirectory(at: work, withIntermediateDirectories: true)
            let patch = package.patches[0]
            try Data("broken backup".utf8).write(to: work.appendingPathComponent(patch.name + "." + patch.sourceSHA256 + ".original"))
            do {
                _ = try SteamCEFPoolPatch.prepare(helper: helper, drive: drive, resource: resource)
                preconditionFailure("corrupt backup accepted")
            } catch SteamCEFPoolPatch.Failure.invalidBackup {}
            try originalPair()
            print("PASS: corrupt original backup rejected before replacing either DLL")
        default: preconditionFailure("unknown fixture action")
        }
    }
}
