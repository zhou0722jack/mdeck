// SPDX-License-Identifier: GPL-3.0-or-later
// Native Steam library preview, following DroidDeck's hero/about/launch layout.
// Upstream references and platform differences: docs/steam-library-client.md.
import SwiftUI

/// Public store information is presentation only. Licences and installation
/// state continue to come from SteamOwnedLibrary and Steam's local manifests.
struct SteamStorePreview: Codable, Equatable {
    var summary: String
    var developers: [String]
    var publishers: [String]
    var screenshots: [URL]

    static func imageURL(_ value: String) -> URL? {
        guard let url = URL(string: value), url.scheme == "https", let host = url.host?.lowercased(),
              ["steamstatic.com", "steamcdn-a.akamaihd.net"].contains(where: { host == $0 || host.hasSuffix("." + $0) }),
              url.user == nil, url.password == nil else { return nil }
        return url
    }

    static func decode(_ data: Data, appID: Int) throws -> Self {
        struct Response: Decodable { var success: Bool; var data: Details? }
        struct Shot: Decodable { var path_full: String }
        struct Details: Decodable {
            var short_description: String?
            var developers: [String]?
            var publishers: [String]?
            var screenshots: [Shot]?
        }
        guard data.count <= 2_000_000,
              let response = try JSONDecoder().decode([String: Response].self, from: data)[String(appID)],
              response.success, let details = response.data else { throw URLError(.cannotParseResponse) }
        let summary = String((details.short_description ?? "").prefix(8000))
            .replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
            .replacingOccurrences(of: "&quot;", with: "\"")
            .replacingOccurrences(of: "&#39;", with: "'")
            .replacingOccurrences(of: "&amp;", with: "&")
            .replacingOccurrences(of: "&lt;", with: "<")
            .replacingOccurrences(of: "&gt;", with: ">")
        return Self(summary: summary, developers: Array((details.developers ?? []).prefix(8)),
                    publishers: Array((details.publishers ?? []).prefix(8)),
                    screenshots: Array((details.screenshots ?? []).prefix(12).compactMap { imageURL($0.path_full) }))
    }

    static func load(appID: Int, refresh: Bool = false) async throws -> Self {
        guard MadeiraDock.validAppID(appID) else { throw URLError(.badURL) }
        let url = URL(string: "https://store.steampowered.com/api/appdetails?appids=\(appID)&l=schinese&filters=basic,screenshots")!
        var request = URLRequest(url: url, cachePolicy: refresh ? .reloadIgnoringLocalCacheData : .returnCacheDataElseLoad, timeoutInterval: 20)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse, response.statusCode == 200 else { throw URLError(.badServerResponse) }
        return try decode(data, appID: appID)
    }
}

struct SteamGamePreviewContent: View {
    let appID: Int
    @State private var preview: SteamStorePreview?
    @State private var failed = false
    @State private var loading = true
    @State private var retry = 0
    @State private var screenshot: PreviewShot?

    private struct PreviewShot: Identifiable { let id: URL }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let preview {
                if !preview.summary.isEmpty {
                    Text("About this game").font(.headline)
                    Text(preview.summary).font(.subheadline).textSelection(.enabled)
                }
                if !preview.developers.isEmpty {
                    LabeledContent("Developer", value: preview.developers.joined(separator: ", "))
                }
                if !preview.publishers.isEmpty {
                    LabeledContent("Publisher", value: preview.publishers.joined(separator: ", "))
                }
                if !preview.screenshots.isEmpty {
                    Text("Screenshots").font(.headline)
                    ScrollView(.horizontal) {
                        HStack(spacing: 12) {
                            ForEach(preview.screenshots, id: \.self) { url in
                                Button { screenshot = PreviewShot(id: url) } label: {
                                    storeImage(url).frame(width: 260, height: 146).clipped()
                                        .clipShape(RoundedRectangle(cornerRadius: 10))
                                }.buttonStyle(.plain).accessibilityLabel("Preview screenshot")
                            }
                        }
                    }
                }
            } else if loading {
                ProgressView("Loading game preview…")
            } else if failed {
                Text("Game preview is unavailable. You can still start an installed game.")
                    .font(.footnote).foregroundStyle(.secondary)
                Button("Retry preview") { retry += 1 }
            }
        }
        .task(id: "\(appID)-\(retry)") {
            loading = true; failed = false; preview = nil
            do {
                let loaded = try await SteamStorePreview.load(appID: appID, refresh: retry > 0)
                try Task.checkCancellation()
                preview = loaded
            } catch {
                guard !Task.isCancelled else { return }
                failed = true
            }
            loading = false
        }
        .sheet(item: $screenshot) { shot in
            NavigationStack {
                storeImage(shot.id).scaledToFit().background(Color.black)
                    .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { screenshot = nil } } }
            }
        }
    }

    private func storeImage(_ url: URL) -> some View {
        AsyncImage(url: url) { phase in
            if let image = phase.image { image.resizable().scaledToFit() }
            else if phase.error != nil { Image(systemName: "photo").frame(maxWidth: .infinity, maxHeight: .infinity) }
            else { ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity) }
        }
    }
}

struct SteamLibraryPreview: View {
    let appID: Int
    let entry: LibraryEntry
    let play: (LibraryEntry) -> Void
    @Environment(\.dismiss) private var dismiss
    @Environment(\.deckPalette) private var palette
    @ObservedObject private var games = SteamGamesModel.shared
    @ObservedObject private var steam = SteamOwnedLibrary.shared
    @ObservedObject private var library = LibraryModel.shared
    @State private var showSettings = false

    private var ready: Bool {
        games.games.first(where: { $0.id == appID })?.installed == true && steam.downloads[appID] == nil
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    ZStack(alignment: .bottomLeading) {
                        SteamGameArtwork(appID: appID, backdrop: true)
                        LinearGradient(colors: [.clear, palette.background.opacity(0.96)], startPoint: .top, endPoint: .bottom)
                        VStack(alignment: .leading, spacing: 10) {
                            Text(entry.title).font(.largeTitle.bold())
                            Label(ready ? L("Installed") : L("Not fully installed"), systemImage: ready ? "checkmark.circle.fill" : "arrow.down.circle")
                                .font(.subheadline).foregroundStyle(ready ? Color.green : Color.orange)
                        }.padding(22)
                    }.frame(height: 290).clipped().clipShape(RoundedRectangle(cornerRadius: 18))
                    HStack(spacing: 12) {
                        Button { play(entry) } label: { Label("Play", systemImage: "play.fill") }
                            .buttonStyle(DeckButtonStyle(primary: true)).disabled(!ready || library.launching)
                        Button { showSettings = true } label: { Label("Game settings", systemImage: "slider.horizontal.3") }
                            .buttonStyle(DeckButtonStyle())
                    }
                    if let download = steam.downloads[appID] { SteamDownloadStatus(download: download) }
                    Text("Steam starts this game by App ID using the global Steam settings. The Steam client handles sign-in, ownership and first-run dependencies.")
                        .font(.footnote).foregroundStyle(palette.muted)
                    SteamGamePreviewContent(appID: appID)
                    if let playtime = steam.playtime[appID]?.summary { Label(playtime, systemImage: "clock") }
                }.padding(22).frame(maxWidth: 1000).frame(maxWidth: .infinity)
            }.background(palette.background).foregroundStyle(palette.text)
                .navigationTitle("Game preview").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
                .sheet(isPresented: $showSettings) { LibraryDetail(entry: entry, play: play) }
                .onAppear { games.refresh() }
        }
    }
}
