#!/usr/bin/env python3
"""Exercise native startup with fake downloads; never contacts a server or builds an IPA."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--static-only', action='store_true')
parser.add_argument('--typecheck-ios', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
startup = (app / 'DeckStartup.swift').read_text()
library = (app / 'Library.swift').read_text()
jit = (app / 'JITSetup.swift').read_text()
project = (root / 'app/Madeira.xcodeproj/project.pbxproj').read_text()
onboarding = (app / 'Onboarding.swift').read_text()

assert not any(name in onboarding + library + jit for name in ['OnboardingModel', 'OnboardingRules', 'OnboardingView', 'Run setup again'])
assert 'struct SteamSettingsSection: View' in onboarding and 'static func dockSession(' in onboarding
assert 'static let launcherChoices: [JITMethod] = [.externalScript, .builtIn]' in jit
assert 'DeckStartupRoot { ContentView() }' in (app / 'MadeiraApp.swift').read_text()
assert 'installAutomatically()' not in (app / 'MadeiraApp.swift').read_text()
assert 'DeckStartup.swift in Sources' in project and 'BootAnimation in Resources' in project
assert '!DeckStartupModel.shared.blocking' in (app / 'SigningRefresh.swift').read_text()
home = library[library.index('    var deckSteamHome:'):library.index('    var deckDesktop:')]
assert home.count('Button {') == 1 and 'install: !SteamClient.installed' in home
assert 'LibraryStatus()' not in home and 'enableJIT' not in home and 'Run Steam installer' not in home
assert 'deckDestination != .library && deckDestination != .steam' in library
assert 'DeckBootSettings()' in library and 'DeckComponentSetupView()' in library
assert 'Button("Skip animation")' not in startup
assert '.onTapGesture(count: 2) { movieFinished = true }' in startup
assert '.accessibilityAction(named: Text("Skip animation"))' in startup
assert 'case .graphics:' in (app / 'SettingsPages.swift').read_text()
print('PASS: old onboarding removed, two JIT choices, one Steam home action, settings retained')

for call in ['WineMonoModel.shared.install()', 'VCRedistModel.shared.install()',
             'WineGeckoModel.shared.install()', 'MadeiraDockModel.shared.prepareClient()']:
    assert call in startup
for forbidden in ['runWineFullSequence', 'URLSession', 'setenv(', 'poolSize', 'send_command(']:
    assert forbidden not in startup, forbidden
assert 'isReady(component)' in startup and 'if complete { defaults.set(true' in startup
assert 'player?.pause()' in startup and 'watchdog?.cancel()' in startup
assert 'view.movieLayer.player = nil' in startup and 'scenePhase == .active' in startup
print('PASS: real verified installers reused; startup has no new Wine, JIT protocol or pool behavior')

manifest = json.loads((root / 'docs/droiddeck-startup-asset.json').read_text())
movie = (app / 'BootAnimation/droiddeck-startup.mp4').read_bytes()
assert hashlib.sha256(movie).hexdigest() == manifest['outputSHA256']
assert b'avc1' in movie and b'mp4a' in movie
assert movie.index(b'moov') < movie.index(b'mdat')
assert (app / 'BootAnimation/LICENSE-DroidDeck.txt').read_bytes() == (app / 'DroidDeckUI/LICENSE-DroidDeck.txt').read_bytes()
assert '6.35' in (app / 'BootAnimation/NOTICE.txt').read_text()
print('PASS: pinned DroidDeck movie, H.264/AAC fast-start container and packaged attribution')
if args.static_only:
    print('SKIP: Swift model execution and iOS typechecking (--static-only)')
    raise SystemExit(0)

model = startup[startup.index('// MARK: - Startup policy'):startup.index('// MARK: - Startup views')]
methods = jit[jit.index('enum JITMethod:'):jit.index('/// Where Built-in')]
fixture = root / 'tests/host/fixtures/DeckStartupStubs.swift'
main = r'''
import Foundation

@main struct Check {
    @MainActor static func wait(_ preparation: DeckComponentPreparation) async {
        for _ in 0..<200 {
            if !preparation.running { return }
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        preconditionFailure("startup download queue did not finish")
    }
    @MainActor static func main() async {
        let name = "mdeck-startup-fixture-" + UUID().uuidString
        let defaults = UserDefaults(suiteName: name)!
        defer { defaults.removePersistentDomain(forName: name) }
        func fresh() -> DeckComponentPreparation {
            StartupFixture.reset()
            defaults.removePersistentDomain(forName: name)
            return DeckComponentPreparation(defaults: defaults)
        }

        var preparation = fresh()
        defaults.set(4, forKey: "madeiraOnboardingRevision")
        var flow = DeckStartupModel(defaults: defaults, preparation: preparation)
        precondition(flow.phase == .chooseJIT, "legacy setup revisions must not skip the new choice")
        flow.choose(.automatic)
        precondition(flow.phase == .chooseJIT && StartupFixture.calls.isEmpty)
        MadeiraBuiltInJIT.isAvailable = false
        flow.choose(.builtIn)
        precondition(flow.phase == .chooseJIT && defaults.string(forKey: DeckStartupRules.choiceKey) == nil)
        flow.choose(.externalScript)
        flow.begin(); flow.begin()
        precondition(defaults.string(forKey: DeckStartupRules.choiceKey) == "externalScript")
        await wait(preparation)
        precondition(flow.phase == .ready && preparation.complete)
        precondition(StartupFixture.calls == DeckSetupComponent.allCases, "install each missing component once in order")
        precondition(defaults.bool(forKey: DeckStartupRules.completeKey))
        StartupFixture.calls = []
        let returning = DeckStartupModel(defaults: defaults, preparation: preparation)
        returning.begin()
        precondition(returning.phase == .ready && StartupFixture.calls.isEmpty)
        print("PASS: first-run choice saved once; returning launches skip setup and downloads")

        preparation = fresh()
        StartupFixture.failures = [.gecko]
        flow = DeckStartupModel(defaults: defaults, preparation: preparation)
        flow.choose(.builtIn)
        await wait(preparation)
        precondition(JITCoordinator.shared.method == .builtIn)
        precondition(flow.phase == .preparing && !preparation.complete)
        precondition(preparation.readyCount == 3 && !defaults.bool(forKey: DeckStartupRules.completeKey))
        guard case .failed("gecko offline") = preparation.states[.gecko] else { preconditionFailure("failure missing") }
        StartupFixture.failures = []; StartupFixture.calls = []
        flow.prepare()
        await wait(preparation)
        precondition(StartupFixture.calls == [.gecko] && flow.phase == .ready)
        precondition(defaults.bool(forKey: DeckStartupRules.completeKey))
        print("PASS: failure stays visible without a completion stamp; retry only downloads the missing component")

        preparation = fresh()
        StartupFixture.failures = [.mono]
        flow = DeckStartupModel(defaults: defaults, preparation: preparation)
        flow.choose(.externalScript)
        flow.deferFailedDownloads()
        precondition(flow.phase == .preparing, "cannot leave while an installer is running")
        await wait(preparation)
        flow.deferFailedDownloads()
        precondition(flow.phase == .ready && !defaults.bool(forKey: DeckStartupRules.completeKey))
        let resumed = DeckStartupModel(defaults: defaults, preparation: preparation)
        precondition(resumed.phase == .preparing, "deferred downloads resume without repeating JIT selection")
        print("PASS: defer never records success; incomplete setup resumes next launch")

        preparation = fresh()
        WineMonoModel.available = true; WineGeckoModel.available = true
        preparation.prepare(); preparation.prepare()
        await wait(preparation)
        precondition(StartupFixture.calls == [.visualCPP, .dock] && preparation.complete)
        print("PASS: existing components are reused and overlapping preparation cannot duplicate downloads")

        preparation = fresh()
        StartupFixture.sessionRunning = true
        preparation.prepare()
        precondition(!preparation.running && !preparation.complete && StartupFixture.calls.isEmpty)
        precondition(!defaults.bool(forKey: DeckStartupRules.completeKey))
        preparation = fresh()
        MadeiraDock.bundled = false; MadeiraDock.clientInstalled = true
        preparation.prepare()
        await wait(preparation)
        precondition(!preparation.complete && preparation.readyCount == 3)
        precondition(!StartupFixture.calls.contains(.dock))
        print("PASS: active sessions and an IPA missing Dock cannot be reported as prepared")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='mdeck-startup-check-') as directory:
    folder = Path(directory)
    production = folder / 'Production.swift'
    production.write_text('import SwiftUI\n' + methods + '\n' + model)
    harness = folder / 'Check.swift'
    harness.write_text(main)
    binary = folder / 'check'
    subprocess.run(['xcrun', 'swiftc', '-parse-as-library', str(production), str(fixture), str(harness), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
    if args.typecheck_ios:
        method_file = folder / 'JITMethod.swift'
        method_file.write_text('import SwiftUI\n' + methods)
        sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
        subprocess.run(['xcrun', 'swiftc', '-typecheck', '-sdk', sdk, '-target', 'arm64-apple-ios18.0',
                        str(app / 'DeckStartup.swift'), str(app / 'DeckDesign.swift'), str(method_file), str(fixture)], check=True)
        print('PASS: production startup views and AVPlayer bridge typechecked against the iOS SDK with dependency stubs')
print('No IPA build, network download, signing, installation or physical-device test performed.')
