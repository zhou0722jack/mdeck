#!/usr/bin/env python3
"""Exercise production store decoding and typecheck native previews/settings; no build."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app/Madeira'
source = (APP / 'SteamLibraryPreview.swift').read_text()
client = (APP / 'SteamClient.swift').read_text()
core = source.split('\nstruct SteamGamePreviewContent:', 1)[0]
settings = client[client.index('struct SteamClientLaunchSettings:'):client.index('\nstruct SteamClientView:')]
fixture = r'''
import SwiftUI
func L(_ value: String) -> String { value }
enum MadeiraDock { static func validAppID(_ value: Int) -> Bool { value > 0 && UInt64(value) < UInt64(UInt32.max) } }
struct LibraryEntry { var title = "Fixture" }
struct InstalledGame { var id: Int; var installed: Bool }
final class SteamGamesModel: ObservableObject {
    static let shared = SteamGamesModel(); @Published var games: [InstalledGame] = []
    func refresh() {}
}
final class SteamOwnedLibrary: ObservableObject {
    struct Download {}
    struct Playtime { var summary: String? }
    static let shared = SteamOwnedLibrary()
    @Published var downloads: [Int: Download] = [:]
    var playtime: [Int: Playtime] = [:]
}
final class LibraryModel: ObservableObject {
    static let shared = LibraryModel(); @Published var launching = false
}
struct SteamGameArtwork: View { let appID: Int; var backdrop = false; var body: some View { Color.gray } }
struct SteamDownloadStatus: View { let download: SteamOwnedLibrary.Download; var body: some View { Color.clear } }
struct LibraryDetail: View { let entry: LibraryEntry; let play: (LibraryEntry) -> Void; var body: some View { Color.clear } }
struct Palette { let background = Color.black, text = Color.white, muted = Color.gray }
struct PaletteKey: EnvironmentKey { static let defaultValue = Palette() }
extension EnvironmentValues { var deckPalette: Palette { get { self[PaletteKey.self] } set { self[PaletteKey.self] = newValue } } }
struct DeckButtonStyle: ButtonStyle {
    var primary = false
    func makeBody(configuration: Configuration) -> some View { configuration.label }
}
enum SteamClient {
    static let bigPictureKey = "fixture.bigPicture", argumentsKey = "fixture.arguments"
    static let extraArguments = "", clientArguments = "-no-cef-sandbox -cef-disable-gpu"
}
enum LaunchArgumentText { static func valid(_ text: String) -> Bool { true } }
'''
main = r'''
import Foundation
@main struct Check {
    static func main() throws {
        let data = Data(#"{"570":{"success":true,"data":{"short_description":"<b>你好</b> &amp; Steam","developers":["Valve"],"publishers":["Valve"],"screenshots":[{"path_full":"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/570/test.jpg"},{"path_full":"http://shared.fastly.steamstatic.com/x.jpg"},{"path_full":"https://steamstatic.com.evil.example/x.jpg"}]}}}"#.utf8)
        let preview = try SteamStorePreview.decode(data, appID: 570)
        precondition(preview.summary == "你好 & Steam" && preview.screenshots.count == 1)
        precondition(preview.developers == ["Valve"])
        func rejects(_ data: Data, _ id: Int = 570) {
            do { _ = try SteamStorePreview.decode(data, appID: id); preconditionFailure("invalid preview accepted") } catch {}
        }
        rejects(data, 730)
        rejects(Data(#"{"570":{"success":false}}"#.utf8))
        rejects(Data("not JSON".utf8))
        rejects(Data(repeating: 32, count: 2_000_001))
        precondition(SteamStorePreview.imageURL("https://evil.example@steamstatic.com/x") == nil)
        let empty = try SteamStorePreview.decode(Data(#"{"570":{"success":true,"data":{}}}"#.utf8), appID: 570)
        precondition(empty.summary.isEmpty && empty.screenshots.isEmpty)
        print("PASS: Chinese preview, HTML cleanup, optional metadata, trusted screenshot URLs, wrong App IDs and unavailable/malformed/oversized responses")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='mdeck-library-preview-') as tmp:
    folder = Path(tmp)
    dependencies = folder / 'Dependencies.swift'
    dependencies.write_text(fixture)
    model = folder / 'Preview.swift'
    model.write_text(core)
    check = folder / 'Check.swift'
    check.write_text(main)
    exe = folder / 'check'
    subprocess.run(['xcrun', 'swiftc', '-parse-as-library', str(dependencies), str(model), str(check), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
    settings_file = folder / 'Settings.swift'
    settings_file.write_text('import SwiftUI\n' + settings)
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    subprocess.run(['xcrun', 'swiftc', '-typecheck', '-sdk', sdk, '-target', 'arm64-apple-ios18.0',
                    str(dependencies), str(APP / 'SteamLibraryPreview.swift'), str(settings_file)], check=True)
print('PASS: native Steam preview, screenshot sheet and global launch controls typecheck against iOS SDK')
print('No network requests, Wine, IPA build or device execution.')
