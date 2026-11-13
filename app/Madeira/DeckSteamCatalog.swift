// SPDX-License-Identifier: GPL-3.0-or-later
// Native port of DroidDeck LibraryPage/LibraryTile/ArtCard, narrowed to Steam.
// Provenance and download contract: docs/steam-only-catalog.md.
import SwiftUI

enum DeckSteamCatalogRules {
    static let scales: [Double] = [0.75, 0.875, 1, 1.2, 1.45]
    enum Filter: String, CaseIterable { case all, installed, notInstalled, downloads }

    static func visible(_ items: [SteamGamesRules.Item], downloads: Set<Int>, filter: Filter,
                        search: String, sort: String, recorded: [Int: SteamGamesRules.Recorded]) -> [SteamGamesRules.Item] {
        let query = search.trimmingCharacters(in: .whitespacesAndNewlines)
        let matching = items.filter { item in
            guard query.isEmpty || item.name.localizedCaseInsensitiveContains(query) else { return false }
            switch filter {
            case .all: return true
            case .installed: return item.installed != nil
            case .notInstalled: return item.installed?.installed != true && !downloads.contains(item.id)
            case .downloads: return downloads.contains(item.id)
            }
        }
        let ordered = SteamGamesRules.sorted(matching, by: sort, recorded: recorded)
        // DroidDeck's installedFirst: keep the selected ordering in each half.
        let onDevice = ordered.filter { $0.installed != nil || downloads.contains($0.id) }
        let other = ordered.filter { $0.installed == nil && !downloads.contains($0.id) }
        return onDevice + other
    }

    static func width(layout: String, level: Int) -> Double {
        (layout == "capsules" ? 120 : 150) * scales[min(scales.count - 1, max(0, level))]
    }
}

struct DeckSteamCatalog: View {
    enum Mode { case library, store }
    let mode: Mode
    let play: (LibraryEntry) -> Void
    let backToLibrary: () -> Void
    @ObservedObject private var steam = SteamOwnedLibrary.shared
    @ObservedObject private var clientSignIn = SteamClientSignInSync.shared
    @ObservedObject private var games = SteamGamesModel.shared
    @ObservedObject private var library = LibraryModel.shared
    @ObservedObject private var appearance = DeckAppearance.shared
    @ObservedObject private var controller = LibraryController.shared
    @Environment(\.deckPalette) private var palette
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduced
    @AppStorage("mdeck.steam.catalog.layout") private var layout = "cards"
    @AppStorage("mdeck.steam.catalog.level") private var level = 2
    @AppStorage("mdeck.steam.catalog.title") private var showTitle = true
    @AppStorage("mdeck.steam.catalog.size") private var showSize = true
    @AppStorage("mdeck.steam.catalog.sort") private var sort = "played"
    @State private var filter: DeckSteamCatalogRules.Filter = .all
    @State private var search = ""
    @State private var selected: Int?
    @State private var focused: Int?
    @State private var columns = 1
    @State private var showSignIn = false
    @State private var showAccountSettings = false
    @State private var downloadOptions: GameSelection?
    @State private var settingsEntry: LibraryEntry?
    @State private var deleteSelection: DockGame?
    @State private var deletedName: String?
    @State private var allItems: [SteamGamesRules.Item] = []
    @State private var visible: [SteamGamesRules.Item] = []
    @State private var recorded: [Int: SteamGamesRules.Recorded] = [:]
    @State private var downloading: Set<Int> = []
    @Namespace private var artwork

    private struct GameSelection: Identifiable { let id: Int }
    private var motion: Animation? { reduced || !appearance.animations ? nil : .spring(response: 0.38, dampingFraction: 0.82) }
    private func records(_ entries: [LibraryEntry], owned: [SteamOwnedGame], playtime: [Int: SteamPlaytime]) -> [Int: SteamGamesRules.Recorded] {
        var records: [Int: SteamGamesRules.Recorded] = [:]
        for (position, entry) in entries.enumerated() {
            if let id = entry.steamAppID {
                records[id] = .init(lastPlayed: entry.lastPlayed, bytes: entry.folderBytes, position: position)
            }
        }
        for game in owned {
            var record = records[game.id] ?? .init(lastPlayed: nil, bytes: nil, position: Int.max)
            if record.bytes == nil { record.bytes = game.installBytes.map { Int64(clamping: $0) } }
            if let time = playtime[game.id], time.lastPlayed > 0 {
                let date = Date(timeIntervalSince1970: TimeInterval(time.lastPlayed))
                record.lastPlayed = max(record.lastPlayed ?? .distantPast, date)
            }
            records[game.id] = record
        }
        return records
    }
    private func arrange() {
        visible = DeckSteamCatalogRules.visible(allItems, downloads: downloading, filter: filter,
                                               search: search, sort: sort, recorded: recorded)
    }

    var body: some View {
        Group {
            if let selected, let item = allItems.first(where: { $0.id == selected }) {
                detail(item).transition(.opacity)
            } else {
                grid.transition(.opacity)
            }
        }
        .background(palette.background).foregroundStyle(palette.text)
        .sheet(isPresented: $showSignIn) { SteamSignInView() }
        .sheet(isPresented: $showAccountSettings) { SteamAccountSettingsView() }
        .sheet(item: $downloadOptions) { selection in
            SteamGameSheet(appID: selection.id) { entry in
                withAnimation(motion) { selected = entry.steamAppID }
            }
        }
        .sheet(item: $settingsEntry) { entry in LibraryDetail(entry: entry, play: play) }
        .confirmationDialog("Delete game?", isPresented: Binding(get: { deleteSelection != nil }, set: { if !$0 { deleteSelection = nil } }),
                            titleVisibility: .visible, presenting: deleteSelection) { game in
            Button("Delete game", role: .destructive) {
                steam.uninstall(game) {
                    withAnimation(motion) { selected = nil }
                    deletedName = game.name
                }
                deleteSelection = nil
            }
            Button("Cancel", role: .cancel) { deleteSelection = nil }
        } message: { game in
            Text(LF("Delete %@? Game files, mods and saves inside its install folder, and local game settings will be deleted. Saves stored elsewhere and Steam account ownership are kept.", game.name))
        }
        .alert("Game deleted", isPresented: Binding(get: { deletedName != nil }, set: { if !$0 { deletedName = nil } })) {
            Button("OK", role: .cancel) { deletedName = nil }
        } message: { Text(LF("%@ has been removed from this device. You can download it again from your Steam library.", deletedName ?? "")) }
        .alert("Steam", isPresented: Binding(get: { steam.error != nil }, set: { if !$0 { steam.error = nil } })) {
            Button("OK", role: .cancel) { steam.error = nil }
        } message: { Text(steam.error ?? "") }
        .task {
            steam.start(); steam.reconcileSession(); games.refresh()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { games.refresh(); steam.reconcileSession(); steam.refreshAfterForeground() }
        }
        .onChange(of: steam.signedIn) { _, _ in selected = nil }
        // Progress updates redraw visible cells, but do not re-merge or sort
        // thousands of owned games on every downloaded chunk.
        .onReceive(steam.$owned.combineLatest(games.$games, steam.$signedIn)) { owned, installed, signedIn in
            let items = SteamGamesRules.items(installed: installed, owned: signedIn ? owned : [], search: "")
            allItems = mode == .store ? items.filter { $0.owned != nil } : items
            arrange()
        }
        .onReceive(library.$entries.combineLatest(steam.$owned, steam.$playtime)) { entries, owned, playtime in
            let next = records(entries, owned: steam.signedIn ? owned : [], playtime: playtime)
            if recorded != next { recorded = next; arrange() }
        }
        .onReceive(steam.$downloads.map { Set($0.keys) }.removeDuplicates()) { ids in
            downloading = ids; arrange()
        }
        .onChange(of: search) { _, _ in arrange() }
        .onChange(of: filter) { _, _ in arrange() }
        .onChange(of: sort) { _, _ in arrange() }
        .onReceive(controller.commands) { command in
            guard !DeckSteamLaunchPreparation.shared.presented, !showSignIn, !showAccountSettings,
                  downloadOptions == nil, settingsEntry == nil, deleteSelection == nil, deletedName == nil,
                  steam.deleting.isEmpty else { return }
            navigate(command)
        }
    }

    private var grid: some View {
        GeometryReader { geometry in
            let list = layout == "list"
            let minimum = DeckSteamCatalogRules.width(layout: layout, level: level)
            let count = list ? 1 : max(1, Int((geometry.size.width - 34) / (minimum + 10)))
            ScrollViewReader { reader in
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        header.modifier(DeckHomeRise(index: 0, enabled: appearance.animations))
                        filters.modifier(DeckHomeRise(index: 1, enabled: appearance.animations))
                        if mode == .store {
                            Text("Download your owned Windows games here. Steam does not need to be running.")
                                .font(.footnote).foregroundStyle(palette.muted)
                        }
                        if !steam.signedIn { signInCard }
                        if steam.signedIn, let text = clientSignIn.statusText {
                            Label(text, systemImage: "arrow.triangle.2.circlepath")
                                .font(.footnote).foregroundStyle(palette.muted)
                        }
                        if steam.signedIn && steam.inSession {
                            Label("Downloads resume after the Windows session ends.", systemImage: "pause.circle")
                                .font(.footnote).foregroundStyle(palette.muted)
                        }
                        if let waiting = steam.cloudWaitingFor {
                            Label(LF("Preparing Steam Cloud for app %@…", String(waiting)), systemImage: "icloud")
                                .font(.footnote).foregroundStyle(palette.muted)
                        }
                        if steam.refreshing { ProgressView("Refreshing Steam library") }
                        if visible.isEmpty && !steam.refreshing { empty }
                        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 10), count: count), spacing: 10) {
                            ForEach(visible) { item in
                                VStack(spacing: 0) {
                                    Button { open(item) } label: {
                                        if list { row(item) } else { tile(item) }
                                    }
                                    .buttonStyle(DeckSteamTileStyle(focused: focused == item.id))
                                    .accessibilityLabel(item.name)
                                    .contextMenu {
                                        if let game = item.installed, SteamInstallPaths.isManaged(library: game.library) {
                                            deleteButton(game)
                                        }
                                    }
                                    if mode == .store {
                                        action(item, compact: true).padding(.top, 6)
                                    }
                                }.id(item.id)
                            }
                        }
                        .modifier(DeckHomeRise(index: 2, enabled: appearance.animations))
                        if mode == .store {
                            Link("Open the official Steam Store", destination: URL(string: "https://store.steampowered.com/")!)
                            Text("After purchasing or adding a game to your Steam account, refresh here to download it.")
                                .font(.footnote).foregroundStyle(palette.muted)
                        }
                    }.padding(geometry.size.width < 600 ? 14 : 22)
                }
                .refreshable { await refresh() }
                .onChange(of: focused) { _, id in if let id { withAnimation(motion) { reader.scrollTo(id, anchor: .center) } } }
                .onAppear { columns = count }
                .onChange(of: count) { _, value in columns = value }
            }
        }
    }

    private var header: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 12) { title; Spacer(); tools }
            VStack(alignment: .leading, spacing: 12) { title; tools }
        }
    }

    private var title: some View {
        HStack(spacing: 10) {
            Text(mode == .library ? L("Library") : L("Steam Store")).font(.title2.bold())
            Text("\(visible.count)").font(.caption.monospacedDigit()).foregroundStyle(palette.muted)
            if steam.signedIn { Image(systemName: "person.crop.circle.badge.checkmark").foregroundStyle(palette.accent).accessibilityLabel("Signed in to Steam") }
        }
    }

    private var tools: some View {
        HStack(spacing: 10) {
            Menu {
                Picker("Filter", selection: $filter) {
                    ForEach(DeckSteamCatalogRules.Filter.allCases, id: \.self) { value in Text(filterTitle(value)).tag(value) }
                }
            } label: { Image(systemName: "line.3.horizontal.decrease") }.accessibilityLabel("Filter")
            Menu {
                Picker("Library layout", selection: $layout) {
                    Text("Cards").tag("cards"); Text("Capsules").tag("capsules"); Text("List").tag("list")
                }
                Button("Larger cards") { level = min(4, level + 1) }.disabled(level >= 4)
                Button("Smaller cards") { level = max(0, level - 1) }.disabled(level <= 0)
                Toggle("Show game titles", isOn: $showTitle)
                Toggle("Show game sizes", isOn: $showSize)
            } label: { Image(systemName: layout == "list" ? "list.bullet" : "square.grid.2x2") }.accessibilityLabel("Library display")
            Menu {
                Picker("Sort by", selection: $sort) {
                    Text("Last played").tag("played"); Text("Name").tag("name"); Text("Folder size").tag("size")
                }
            } label: { Image(systemName: "arrow.up.arrow.down") }.accessibilityLabel("Sort by")
            Button { Task { await refresh() } } label: { Image(systemName: "arrow.clockwise") }.disabled(steam.refreshing).accessibilityLabel("Refresh Steam library")
            Button { showAccountSettings = true } label: { Image(systemName: "person.crop.circle") }.accessibilityLabel("Steam account and downloads")
            Button { clientSignIn.rereadInstalledSignIn() } label: {
                HStack(spacing: 6) {
                    if clientSignIn.phase == .validating { ProgressView().controlSize(.small) }
                    else { Image(systemName: "arrow.triangle.2.circlepath") }
                    Text("Read Steam sign-in").font(.subheadline)
                }
            }
            .disabled(clientSignIn.phase == .validating)
            .accessibilityLabel("Read Steam sign-in")
            .accessibilityHint("Recheck the installed Windows Steam sign-in.")
            .accessibilityIdentifier("steam-reread-installed-signin")
        }.font(.system(size: 18)).buttonStyle(.borderless).frame(minHeight: 36)
    }

    private var filters: some View {
        VStack(spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass").foregroundStyle(palette.muted)
                TextField("Search Steam games", text: $search).textInputAutocapitalization(.never).autocorrectionDisabled()
                if !search.isEmpty { Button { search = "" } label: { Image(systemName: "xmark.circle.fill") }.accessibilityLabel("Clear search") }
            }.padding(12).background(palette.surface, in: RoundedRectangle(cornerRadius: 10))
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    Label("Steam", systemImage: "gamecontroller").font(.system(size: 13, weight: .bold))
                        .padding(.horizontal, 14).padding(.vertical, 9).background(palette.accent.opacity(0.16), in: Capsule())
                    ForEach(DeckSteamCatalogRules.Filter.allCases, id: \.self) { value in
                        Button { withAnimation(motion) { filter = value } } label: {
                            Text(filterTitle(value)).font(.system(size: 13, weight: .bold))
                                .padding(.horizontal, 14).padding(.vertical, 9)
                                .background(filter == value ? palette.accent.opacity(0.16) : palette.surface, in: Capsule())
                        }.buttonStyle(.plain).accessibilityAddTraits(filter == value ? .isSelected : [])
                    }
                }
            }
        }
    }

    private var signInCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let text = clientSignIn.statusText {
                HStack(spacing: 10) {
                    if clientSignIn.phase == .validating { ProgressView() }
                    else { Image(systemName: clientSignIn.phase == .failed ? "exclamationmark.circle" : "info.circle") }
                    Text(text).font(.footnote)
                }
            }
        Button { showSignIn = true } label: {
            HStack(spacing: 12) {
                Image(systemName: "person.crop.circle.badge.plus").font(.title2)
                VStack(alignment: .leading, spacing: 4) {
                    Text(clientSignIn.hasPendingAuthorization ? L("Use another sign-in method") : L("Sign in to Steam")).font(.headline)
                    Text("Sign in once in Windows Steam. Your account will sync here automatically.").font(.footnote).foregroundStyle(palette.muted)
                }
                Spacer(); Image(systemName: "chevron.right")
            }.padding(16).background(palette.surface, in: RoundedRectangle(cornerRadius: 12))
        }.buttonStyle(.plain)
        }
    }

    private var empty: some View {
        VStack(spacing: 12) {
            Image(systemName: "rectangle.stack").font(.system(size: 48, weight: .ultraLight)).foregroundStyle(palette.muted)
            Text(search.isEmpty ? L("No Steam games in this view.") : L("No games match your search.")).font(.headline)
            if steam.signedIn { Button("Refresh Steam library") { Task { await refresh() } }.buttonStyle(DeckButtonStyle()) }
            if mode == .store {
                Link("Open the official Steam Store", destination: URL(string: "https://store.steampowered.com/")!)
                Text("After purchasing or adding a game to your Steam account, refresh here to download it.")
                    .font(.footnote).foregroundStyle(palette.muted).multilineTextAlignment(.center)
            }
        }.frame(maxWidth: .infinity).padding(.vertical, 36)
    }

    private func tile(_ item: SteamGamesRules.Item) -> some View {
        ZStack(alignment: .bottomLeading) {
            SteamGameArtwork(appID: item.id, backdrop: layout != "capsules")
                .matchedGeometryEffect(id: item.id, in: artwork)
            LinearGradient(colors: [.clear, .black.opacity(0.92)], startPoint: .center, endPoint: .bottom)
            VStack(alignment: .leading, spacing: 3) {
                if showTitle || focused == item.id { Text(item.name).font(.system(size: 11, weight: .bold)).lineLimit(focused == item.id ? 2 : 1) }
                if showSize || focused == item.id, let size = size(item) { Text(size).font(.system(size: 10)).foregroundStyle(.white.opacity(0.75)) }
                if let download = steam.downloads[item.id] { ProgressView(value: download.progress.fraction).tint(palette.accent) }
            }.padding(8).foregroundStyle(.white)
        }
        .aspectRatio(layout == "capsules" ? 5.0 / 7 : 16.0 / 9, contentMode: .fit)
        .overlay(alignment: .topTrailing) { badge(item).padding(6) }
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private func row(_ item: SteamGamesRules.Item) -> some View {
        HStack(spacing: 12) {
            SteamGameArtwork(appID: item.id, backdrop: true).matchedGeometryEffect(id: item.id, in: artwork)
                .frame(width: 96, height: 54).clipShape(RoundedRectangle(cornerRadius: 8))
            VStack(alignment: .leading, spacing: 4) {
                Text(item.name).font(.subheadline.bold()).lineLimit(2)
                if let size = size(item) { Text(size).font(.caption).foregroundStyle(palette.muted) }
                if let download = steam.downloads[item.id] { ProgressView(value: download.progress.fraction) }
            }
            Spacer(); badge(item)
        }.padding(8).background(palette.surface, in: RoundedRectangle(cornerRadius: 10))
    }

    @ViewBuilder private func badge(_ item: SteamGamesRules.Item) -> some View {
        let state = SteamGamesRules.status(installed: item.installed, transfer: steam.downloads[item.id]?.transfer,
                                          updateAvailable: steam.updateAvailable(appID: item.id, installedBuild: games.builds[item.id], installedBranch: games.branches[item.id]))
        if let text = steam.deleting.contains(item.id) ? L("Deleting game…") : state.badge {
            Text(text).font(.system(size: 10, weight: .semibold)).padding(.horizontal, 7).padding(.vertical, 4)
                .foregroundStyle(.white).background(.black.opacity(0.7), in: Capsule())
        }
    }

    private func detail(_ item: SteamGamesRules.Item) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Button { withAnimation(motion) { selected = nil } } label: { Label("Back to games", systemImage: "chevron.left") }.buttonStyle(DeckButtonStyle())
                ZStack(alignment: .bottomLeading) {
                    SteamGameArtwork(appID: item.id, backdrop: true).matchedGeometryEffect(id: item.id, in: artwork)
                    LinearGradient(colors: [.clear, palette.background.opacity(0.96)], startPoint: .top, endPoint: .bottom)
                    VStack(alignment: .leading, spacing: 10) {
                        Text(item.name).font(.system(size: 34, weight: .bold)).lineLimit(3)
                        HStack { action(item); downloadOptionsButton(item) }
                    }.padding(22)
                }.frame(height: 300).clipped().clipShape(RoundedRectangle(cornerRadius: 10))
                if let download = steam.downloads[item.id] { SteamDownloadStatus(download: download) }
                if let installed = item.installed {
                    Button { settingsEntry = library.steamEntry(installed, title: item.name) } label: {
                        Label("Game settings", systemImage: "slider.horizontal.3")
                    }.buttonStyle(DeckButtonStyle())
                        .disabled(steam.deleting.contains(item.id))
                    if SteamInstallPaths.isManaged(library: installed.library) {
                        deleteButton(installed).buttonStyle(DeckButtonStyle())
                        if deletionBlocked {
                            Text("End the Windows session before deleting a game.")
                                .font(.footnote).foregroundStyle(palette.muted)
                        }
                    }
                }
                if let size = size(item) { Label(size, systemImage: "internaldrive") }
                if let playtime = steam.playtime[item.id]?.summary { Label(playtime, systemImage: "clock") }
                SteamGamePreviewContent(appID: item.id)
                Link("View in the Steam Store", destination: URL(string: "https://store.steampowered.com/app/\(item.id)/")!)
            }.padding(22).frame(maxWidth: 1100).frame(maxWidth: .infinity)
        }.refreshable { await refresh() }
    }

    private func downloadOptionsButton(_ item: SteamGamesRules.Item) -> some View {
        Button { downloadOptions = GameSelection(id: item.id) } label: {
            Label("Download options", systemImage: "arrow.down.circle")
        }.buttonStyle(DeckButtonStyle()).disabled(steam.deleting.contains(item.id))
    }

    private var deletionBlocked: Bool {
        steam.inSession || library.current != nil || library.startingScreen || DeckSteamLaunchPreparation.shared.presented
    }

    private func deleteButton(_ game: DockGame) -> some View {
        Button(role: .destructive) { deleteSelection = game } label: {
            Label("Delete game", systemImage: "trash").foregroundStyle(.red)
        }
        .disabled(deletionBlocked || !steam.deleting.isEmpty)
        .accessibilityIdentifier("steam-delete-game-\(game.id)")
    }

    @ViewBuilder private func action(_ item: SteamGamesRules.Item, compact: Bool = false) -> some View {
        if steam.deleting.contains(item.id) {
            ProgressView("Deleting game…")
        } else if let download = steam.downloads[item.id] {
            switch download.state {
            case .active, .queued:
                Button { steam.pause(item.id) } label: { Label("Pause", systemImage: "pause.fill") }.buttonStyle(DeckButtonStyle())
            case .paused, .failed:
                Button { steam.install(item.id) } label: { Label("Resume download", systemImage: "arrow.down.circle") }
                    .buttonStyle(DeckButtonStyle(primary: !compact)).disabled(!steam.signedIn)
            }
        } else if let installed = item.installed, installed.installed {
            Button { play(library.steamEntry(installed, title: item.name)) } label: { Label("Play", systemImage: "play.fill") }
                .buttonStyle(DeckButtonStyle(primary: !compact)).disabled(library.launching || !steam.deleting.isEmpty)
        } else if item.owned != nil {
            Button { steam.install(item.id) } label: { Label("Download", systemImage: "arrow.down.circle") }
                .buttonStyle(DeckButtonStyle(primary: !compact)).disabled(!steam.signedIn)
        }
    }

    private func size(_ item: SteamGamesRules.Item) -> String? {
        let bytes = recorded[item.id]?.bytes ?? item.owned?.installBytes.map { Int64(clamping: $0) }
        return bytes.map { ByteCountFormatter.string(fromByteCount: $0, countStyle: .file) }
    }

    private func filterTitle(_ value: DeckSteamCatalogRules.Filter) -> String {
        switch value {
        case .all: return L("All games")
        case .installed: return L("Installed")
        case .notInstalled: return L("Not installed")
        case .downloads: return L("Downloads")
        }
    }

    private func open(_ item: SteamGamesRules.Item) {
        focused = item.id
        withAnimation(motion) { selected = item.id }
    }

    private func refresh() async {
        games.refresh()
        if steam.signedIn { await steam.refreshLibrary(interactive: true) }
    }

    private func navigate(_ command: String) {
        if command == "back" {
            if selected != nil { withAnimation(motion) { selected = nil } }
            else if mode == .store { backToLibrary() }
            return
        }
        guard selected == nil else {
            if command == "accept", let id = selected, let item = allItems.first(where: { $0.id == id }),
               let game = item.installed, game.installed, steam.downloads[id] == nil {
                play(library.steamEntry(game, title: item.name))
            }
            return
        }
        let items = visible
        guard !items.isEmpty else { return }
        let index = items.firstIndex { $0.id == focused } ?? 0
        if command == "accept" { open(items[index]); return }
        let delta: Int
        switch command {
        case "left": delta = -1
        case "right": delta = 1
        case "up": delta = -columns
        case "down": delta = columns
        default: return
        }
        focused = items[min(items.count - 1, max(0, index + delta))].id
    }
}

private struct DeckSteamTileStyle: ButtonStyle {
    let focused: Bool
    @State private var hovered = false
    @Environment(\.deckPalette) private var palette
    @Environment(\.accessibilityReduceMotion) private var reduced
    @ObservedObject private var appearance = DeckAppearance.shared
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(focused || hovered ? palette.accent : palette.line, lineWidth: focused || hovered ? 2 : 1))
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
            .animation(reduced || !appearance.animations ? nil : .spring(response: 0.28, dampingFraction: 0.5), value: configuration.isPressed)
            .onHover { hovered = $0 }
    }
}

struct DeckSteamCatalogDisplaySettings: View {
    @AppStorage("mdeck.steam.catalog.layout") private var layout = "cards"
    @AppStorage("mdeck.steam.catalog.level") private var level = 2
    @AppStorage("mdeck.steam.catalog.title") private var showTitle = true
    @AppStorage("mdeck.steam.catalog.size") private var showSize = true
    var body: some View {
        Section {
            Picker("Library layout", selection: $layout) {
                Text("Cards").tag("cards"); Text("Capsules").tag("capsules"); Text("List").tag("list")
            }
            Stepper(value: $level, in: 0...4) { LabeledContent("Card size", value: "\(min(4, max(0, level)) + 1) / 5") }
            Toggle("Show game titles", isOn: $showTitle)
            Toggle("Show game sizes", isOn: $showSize)
        } header: { Text("Library display") } footer: {
            Text("The Steam library and store share these display settings.")
        }
    }
}
