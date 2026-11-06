// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright 2026 125hz
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import SwiftUI

// MARK: - Settings › Steam

/// The library's Steam settings: the signed-in account, Sign in / Sign out
/// (SteamSignIn; the token stays in its Keychain store), Madeira Dock's sheet
/// and its existing account and download settings.
struct SteamSettingsSection: View {
    /// Opens Steam sign-in or Madeira Dock. LibraryView presents the sheet from the
    /// Settings Form: a sheet attached to this section closed again as soon as it
    /// slid up whenever the Form rebuilt its rows.
    let open: (SettingsSheet) -> Void
    @ObservedObject private var signIn = SteamSignInModel.shared
    @ObservedObject private var dock = MadeiraDockModel.shared
    @ObservedObject private var cloud = SteamCloudSetting.shared
    @State private var confirmSignOut = false
    /// Settings › Steam › Game language (SteamLanguage); "" follows the device.
    @State private var language = SteamLanguage.chosen ?? ""
    /// Settings › Steam › Downloads from PCs on this network (SteamLANSetting).
    @State private var lanOn = SteamLANSetting.enabled
    /// A fixed PC address; "" finds the PC through Steam.
    @State private var lanHost = SteamLANSetting.host

    /// Shown when Steam sign-in or Madeira Dock is available.
    static var shown: Bool { SteamSignIn.isEnabled || MadeiraDock.enabled }

    var body: some View {
        Section {
            if let name = signIn.accountName {
                LabeledContent("Signed in as", value: name)
                Button("Sign out of Steam", role: .destructive) { confirmSignOut = true }
            } else {
                Button { open(.steamSignIn) } label: { Label("Sign in to Steam", systemImage: "person.crop.circle.badge.plus") }
            }
            Picker("Game language", selection: $language) {
                Text(LF("Device language (%@)", String(describing: (SteamLanguage.name(SteamLanguage.device))))).tag("")
                ForEach(SteamLanguage.all, id: \.code) { Text($0.name).tag($0.code) }
            }
            .pickerStyle(.navigationLink)
            .onChange(of: language) { _, value in SteamLanguage.choose(value.isEmpty ? nil : value) }
            // Off: no Steam Cloud checks, transfers or prompts before Play (docs/STEAM_CLOUD.md).
            if SteamOwnedLibrary.enabled {
                Toggle("Steam Cloud saves", isOn: $cloud.on)
                Toggle("Downloads from PCs on this network", isOn: $lanOn)
                    .onChange(of: lanOn) { _, value in SteamLANSetting.enabled = value }
                if lanOn {
                    LabeledContent("PC address") {
                        TextField("Automatic", text: $lanHost)
                            .keyboardType(.decimalPad)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .multilineTextAlignment(.trailing)
                            .foregroundStyle(lanHost.isEmpty || SteamLANSetting.isValidAddress(lanHost) ? Color.primary : Color.red)
                    }
                    .onChange(of: lanHost) { _, value in
                        let trimmed = value.trimmingCharacters(in: .whitespaces)
                        if trimmed.isEmpty || SteamLANSetting.isValidAddress(trimmed) { SteamLANSetting.host = trimmed }
                    }
                }
            }
            if MadeiraDock.enabled {
                Button { open(.dock) } label: { Label("Madeira Dock", systemImage: "shippingbox") }
                if let status = dock.status {
                    Text(status).font(.caption).foregroundStyle(.secondary)
                }
            }
        } header: {
            Text("Steam")
        } footer: {
            Text("Game language: the language Steam downloads install, and the one Steam tells the game to use. A game without it gets English. Installed games keep their language until you choose Download in their page.\n\nDownloads from PCs on this network: a game's download comes first from a PC on the same network whose Steam has it installed and up to date, through Steam's local network game transfers (Steam on the PC: same account, Settings › Downloads › Game file transfer over local network on, no download or game running). Anything the PC does not have comes from Steam's servers. Madeira finds the PC through Steam and shows up in the account's devices as \"Madeira\". PC address: only when the PC is not found; its IP address on this network.\n\nMadeira keeps a Steam sign-in token in this device's Keychain, for this device only. Signing out removes it.")
        }
        .confirmationDialog("Sign out of Steam?", isPresented: $confirmSignOut, titleVisibility: .visible) {
            Button("Sign out", role: .destructive) { signIn.signOut() }
        }
        .onAppear { signIn.refresh() }
        .onReceive(NotificationCenter.default.publisher(for: SteamSignIn.didChange)) { _ in signIn.refresh() }
    }
}

// MARK: - Madeira Dock in the library

extension LibraryEntry {
    static let dockSessionID = UUID(uuidString: "5D0C4A3E-2B7F-4C61-9E0A-6B1D2F3C4E5A")!

    /// A Dock start from the library runs as a library session (full-screen
    /// view, starting screen, in-game menu, one session per run) with this
    /// entry. It is a desktop session: explorer's virtual desktop runs the
    /// host. It is never saved to the library.
    static func dockSession(title: String, width: Int, height: Int) -> LibraryEntry {
        var entry = LibraryEntry(title: title.isEmpty ? "Madeira Dock" : title, relativePath: "windows/system32/explorer.exe", bits: 64)
        entry.id = dockSessionID; entry.desktop = true; entry.resolution = "\(width)x\(height)"
        entry.graphicsAPI = "Madeira Dock"
        return entry
    }
}
