#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Exercise the production uninstall coordinator with synthetic tasks and storage failures."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app/Madeira'
source = (APP / 'SteamOwnedLibrary.swift').read_text()


def block(text, header):
    start = text.index(header)
    opening = text.index('{', start)
    end, depth = opening + 1, 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


method = block(source, '    func uninstall(_ game: DockGame,')
assert '@Published private(set) var deleting: Set<Int>' in source
catalog = (APP / 'DeckSteamCatalog.swift').read_text()
assert '.confirmationDialog("Delete game?"' in catalog
assert '.contextMenu {' in catalog and 'deleteButton(installed)' in catalog
assert 'steam.uninstall(game) {' in catalog and 'ProgressView("Deleting game…")' in catalog
settings = (APP / 'SteamGames.swift').read_text()
assert 'steam.uninstall(installed, onRemoved: uninstalled)' in settings
content = (APP / 'ContentView.swift').read_text()
for header in ('private func launchLibraryEntry(', 'private func startLibraryEntry('):
    assert 'guard SteamOwnedLibrary.shared.deleting.isEmpty' in block(content, header)

stubs = r'''
import Foundation
func L(_ text: String) -> String { text }
struct DockGame { var id = 9000; var library = "managed"; var installDir = "Game" }
enum SteamInstallPaths { static func isManaged(library: String) -> Bool { library == "managed" } }
enum ExternalDrives {
    static func nativeURL(_ library: String, write: Bool) throws -> URL { URL(fileURLWithPath: "/unused-fixture") }
}
enum SteamInstallFiles {
    nonisolated(unsafe) static var fails = false
    nonisolated(unsafe) static var calls = 0
    static func delete(appID: Int, folderName: String, steamApps: URL) throws {
        calls += 1
        if fails { throw CocoaError(.fileWriteNoPermission) }
    }
}
@MainActor final class LibraryModel {
    static let shared = LibraryModel()
    var current: UUID?
    var startingScreen = false
    var removed: [Int] = []
    func removeSteam(appID: Int) { removed.append(appID) }
}
@MainActor final class DeckSteamLaunchPreparation {
    static let shared = DeckSteamLaunchPreparation(); var presented = false
}
@MainActor final class GameMover { static let shared = GameMover(); var moving: Int? }
@MainActor final class SteamGamesModel {
    static let shared = SteamGamesModel(); var refreshes = 0
    func refresh() { refreshes += 1 }
}
@MainActor enum DockInstallers {
    static var resets: [Int] = []
    static func setRunsNext(_ id: Int, _ value: Bool, prefix: URL) { resets.append(id) }
}
enum MadeiraDock { static let prefix = URL(fileURLWithPath: "/unused-fixture") }
@MainActor enum SteamLog { static var events: [String] = []; static func event(_ text: String) { events.append(text) } }
struct Cloud { enum Phase { case checking, done }; var phase: Phase }
@MainActor final class SteamOwnedLibrary {
    var inSession = false
    var deleting: Set<Int> = []
    var cloudBusy: Set<Int> = []
    var cloud: [Int: Cloud] = [:]
    var active: (id: Int, task: Task<Void, Never>)?
    var downloads: [Int: String] = [9000: "paused"]
    var targets: [Int: String] = [9000: "managed"]
    var error: String?
    var pauses = 0
    func pause(_ id: Int) { pauses += 1; active?.task.cancel(); downloads[id] = "paused" }
    func setTarget(_ id: Int, _ value: String?) { targets[id] = value }
'''
checks = r'''
}
@MainActor final class Gate {
    var continuation: CheckedContinuation<Void, Never>?
    func wait() async { await withCheckedContinuation { continuation = $0 } }
    func release() { continuation?.resume(); continuation = nil }
}
@main struct Checks {
    @MainActor static func settle(_ library: SteamOwnedLibrary) async {
        for _ in 0..<2000 {
            if library.deleting.isEmpty { return }
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
        preconditionFailure("uninstall did not finish")
    }
    @MainActor static func main() async {
        let game = DockGame()
        // These guards must run before pausing downloads or scheduling file work.
        for gate in 0..<9 {
            let library = SteamOwnedLibrary()
            var selected = game
            if gate == 0 { selected.library = "unmanaged" }
            if gate == 1 { library.inSession = true }
            if gate == 2 { LibraryModel.shared.current = UUID() }
            if gate == 3 { LibraryModel.shared.startingScreen = true }
            if gate == 4 { DeckSteamLaunchPreparation.shared.presented = true }
            if gate == 5 { library.deleting.insert(game.id) }
            if gate == 6 { library.cloudBusy.insert(game.id) }
            if gate == 7 { library.cloud[game.id] = Cloud(phase: .checking) }
            if gate == 8 { GameMover.shared.moving = game.id }
            var callback = false
            library.uninstall(selected) { callback = true }
            precondition(library.error != nil && library.pauses == 0 && !callback)
            precondition(SteamInstallFiles.calls == 0 && LibraryModel.shared.removed.isEmpty)
            LibraryModel.shared.current = nil; LibraryModel.shared.startingScreen = false
            DeckSteamLaunchPreparation.shared.presented = false; GameMover.shared.moving = nil
        }
        print("PASS: invalid library, active/starting Windows session, duplicate delete, cloud and move guards")

        let library = SteamOwnedLibrary(), gate = Gate()
        let download = Task { @MainActor in await gate.wait() }
        while gate.continuation == nil { await Task.yield() }
        library.active = (game.id, download)
        var callbacks = 0
        library.uninstall(game) { callbacks += 1 }
        precondition(library.deleting.contains(game.id) && library.pauses == 1)
        for _ in 0..<10 { await Task.yield() }
        precondition(download.isCancelled && SteamInstallFiles.calls == 0 && callbacks == 0)
        precondition(library.downloads[game.id] != nil && LibraryModel.shared.removed.isEmpty)
        gate.release()
        await settle(library)
        precondition(callbacks == 1 && SteamInstallFiles.calls == 1)
        precondition(library.downloads.isEmpty && library.targets.isEmpty)
        precondition(LibraryModel.shared.removed == [game.id] && DockInstallers.resets == [game.id])
        precondition(SteamGamesModel.shared.refreshes == 1 && library.error == nil)
        print("PASS: download stops before removal; settings, target and download clear only after success; one callback and rescan")

        SteamInstallFiles.fails = true
        let failed = SteamOwnedLibrary()
        failed.uninstall(game) { callbacks += 1 }
        await settle(failed)
        precondition(callbacks == 1 && failed.error?.hasPrefix("The install could not be removed:") == true)
        precondition(failed.downloads[game.id] != nil && failed.targets[game.id] != nil)
        precondition(LibraryModel.shared.removed == [game.id] && SteamGamesModel.shared.refreshes == 1)
        precondition(SteamLog.events.contains { $0.contains("uninstall failed app=9000") })
        print("PASS: storage failure keeps local settings and paused download, reports error and never signals success")

        SteamInstallFiles.fails = false
        let raced = SteamOwnedLibrary(), secondGate = Gate()
        let secondDownload = Task { @MainActor in await secondGate.wait() }
        while secondGate.continuation == nil { await Task.yield() }
        raced.active = (game.id, secondDownload)
        raced.uninstall(game) { callbacks += 1 }
        LibraryModel.shared.current = UUID()
        secondGate.release()
        await settle(raced)
        precondition(SteamInstallFiles.calls == 2 && callbacks == 1 && raced.error != nil)
        precondition(raced.downloads[game.id] != nil && raced.targets[game.id] != nil)
        print("PASS: Windows session starting while a download stops prevents file deletion")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='mdeck-uninstall-') as tmp:
    folder = Path(tmp)
    harness, binary = folder / 'Uninstall.swift', folder / 'check'
    harness.write_text(stubs + method + checks)
    subprocess.run(['xcrun', 'swiftc', '-parse-as-library', str(harness), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('PASS: production uninstall coordination and catalog/settings/launch wiring; no real game data touched')
