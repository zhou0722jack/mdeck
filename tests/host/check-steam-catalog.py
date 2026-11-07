#!/usr/bin/env python3
"""Exercise Steam-only catalog ordering and typecheck the native DroidDeck port."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app/Madeira'
source = (APP / 'DeckSteamCatalog.swift').read_text()
games = (APP / 'SteamGames.swift').read_text()

def block(text, header):
    start = text.index(header)
    brace = text.index('{', start)
    end, depth = brace + 1, 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

rules = 'import Foundation\n' + block(games, 'enum SteamGamesRules {')
catalog_rules = source.split('\nstruct DeckSteamCatalog:', 1)[0]
main = r'''
import Foundation
@main struct Check {
    static func main() {
        let owned = [SteamOwnedGame(id: 1, name: "Alpha"), SteamOwnedGame(id: 2, name: "Beta"),
                     SteamOwnedGame(id: 3, name: "Gamma"), SteamOwnedGame(id: 4, name: "Delta")]
        let items = SteamGamesRules.items(installed: [DockGame(id: 2, installed: true), DockGame(id: 3, installed: false)],
                                         owned: owned, search: "")
        let records: [Int: SteamGamesRules.Recorded] = [2: .init(lastPlayed: Date(timeIntervalSince1970: 20), bytes: 50, position: 0),
                                                      3: .init(lastPlayed: Date(timeIntervalSince1970: 30), bytes: 100, position: 1)]
        func ids(_ filter: DeckSteamCatalogRules.Filter, _ search: String = "", _ sort: String = "name") -> [Int] {
            DeckSteamCatalogRules.visible(items, downloads: [4], filter: filter, search: search, sort: sort, recorded: records).map(\.id)
        }
        precondition(ids(.all) == [2, 4, 3, 1])
        precondition(ids(.installed) == [2, 3])
        precondition(ids(.notInstalled) == [3, 1])
        precondition(ids(.downloads) == [4])
        precondition(ids(.all, "  ALPHA  ") == [1])
        precondition(ids(.all, "unmatched").isEmpty)
        precondition(ids(.all, "", "played").prefix(2) == [3, 2])
        precondition(ids(.all, "", "size").prefix(2) == [3, 2])
        precondition(DeckSteamCatalogRules.width(layout: "cards", level: -1) == 112.5)
        precondition(DeckSteamCatalogRules.width(layout: "capsules", level: 99) == 174)
        let local = SteamGamesRules.items(installed: [DockGame(id: 2, installed: true)], owned: [], search: "")
        precondition(local.map(\.id) == [2] && local.first?.owned == nil)
        print("PASS: Steam owned/local merging, installed-first ordering, partial/queued download filters, search, recent/size sorts and five bounded card sizes")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='mdeck-steam-catalog-') as tmp:
    folder = Path(tmp)
    rules_file, model, harness = folder / 'Rules.swift', folder / 'Catalog.swift', folder / 'Check.swift'
    rules_file.write_text(rules)
    model.write_text(catalog_rules)
    harness.write_text(main)
    fixture = ROOT / 'tests/host/fixtures/SteamCatalogStubs.swift'
    binary = folder / 'check'
    subprocess.run(['xcrun', 'swiftc', '-parse-as-library', str(fixture), str(rules_file), str(model), str(harness), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    subprocess.run(['xcrun', 'swiftc', '-typecheck', '-sdk', sdk, '-target', 'arm64-apple-ios18.0',
                    str(fixture), str(rules_file), str(APP / 'DeckSteamCatalog.swift')], check=True)
print('PASS: Steam catalog, inline detail transitions, all layouts, download actions and controller navigation typecheck against iOS SDK')
print('No IPA build, account login or real game download performed.')
