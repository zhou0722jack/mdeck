// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation

enum SteamClientRuntimeFailure {
    static let runKey = "mdeck.steam.runtime.run"
    static func beginRun() {
        let run = UUID().uuidString
        UserDefaults.standard.set(run, forKey: runKey)
        setenv("MADEIRA_STEAM_RUN_ID", run, 1)
    }
    static func matchesActiveRun(_ run: String) -> Bool {
        UUID(uuidString: run) != nil && run == UserDefaults.standard.string(forKey: runKey)
    }
}

#if canImport(UIKit)
@_cdecl("madeira_steam_initial_window_failure")
func madeiraSteamInitialWindowFailure(_ run: UnsafePointer<CChar>?) {
    guard let run, strnlen(run, 37) == 36 else { return }
    let identity = String(cString: run)
    Task { @MainActor in
        guard SteamClientRuntimeFailure.matchesActiveRun(identity),
              let session = LibraryModel.shared.current,
              let entry = LibraryModel.shared.activeEntry,
              SteamClient.owns(entry) || entry.desktop == true,
              DeckSteamLaunchPreparation.shared.awaitingClientImage else { return }
        let message = L("Steam could not create its initial update window and exited (-104). The app has stopped waiting for its first frame. Close the session and share the log.")
        LogStore.shared.log("[steam-startup] initial update window failure reported; first-frame wait stopped")
        DeckSteamLaunchPreparation.shared.runtimeFailure(message, session: session)
        LibraryModel.shared.error = message
    }
}

@_cdecl("madeira_steam_cef_address_failure")
func madeiraSteamCEFAddressFailure(_ run: UnsafePointer<CChar>?) {
    guard let run, strnlen(run, 37) == 36 else { return }
    let identity = String(cString: run)
    Task { @MainActor in
        guard SteamClientRuntimeFailure.matchesActiveRun(identity),
              let session = LibraryModel.shared.current,
              let entry = LibraryModel.shared.activeEntry,
              SteamClient.owns(entry) || entry.desktop == true else { return }
        let message = L("The 64-bit Steam web interface could not reserve its required continuous address space. Automatic restarts have stopped for this session. Close the session and share the log.")
        LogStore.shared.log("[steam-cef] address-space initialization failure reported; automatic helper restarts stopped")
        DeckSteamLaunchPreparation.shared.runtimeFailure(message, session: session)
        LibraryModel.shared.error = message
    }
}
#endif
