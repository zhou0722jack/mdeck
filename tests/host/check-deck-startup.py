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
assert '!DeckSteamLaunchPreparation.shared.presented' in (app / 'SigningRefresh.swift').read_text()
home = library[library.index('    var deckSteamHome:'):library.index('    var deckDesktop:')]
assert home.count('Button {') == 3 and 'install: !SteamClient.installed' in home
assert 'steamArchitectureButton(.x86' in home and 'steamArchitectureButton(.x64' in home
assert 'Text("Experimental feature")' in home and 'steamArchitecture = architecture.rawValue' in home
assert 'Label("Steam settings"' in home and 'DeckSettingsRoute(page: .steam)' in home
assert 'LibraryStatus()' not in home and 'enableJIT' not in home and 'Run Steam installer' not in home
assert 'deckDestination != .library && deckDestination != .steam' in library
assert 'DeckBootSettings()' in library and 'DeckComponentSetupView()' in library
assert 'Button("Skip animation")' not in startup
assert '.onTapGesture(count: 2) { movieFinished = true }' in startup
assert '.accessibilityAction(named: Text("Skip animation"))' in startup
assert 'case .graphics:' in (app / 'SettingsPages.swift').read_text()
print('PASS: old onboarding removed, two JIT choices, Steam launch and global settings on home')

for call in ['WineMonoModel.shared.install()', 'VCRedistModel.shared.install()',
             'WineGeckoModel.shared.install()']:
    assert call in startup
assert 'MadeiraDock' not in startup and 'case mono, visualCPP, gecko' in startup
for forbidden in ['runWineFullSequence', 'URLSession', 'setenv(', 'poolSize', 'send_command(']:
    assert forbidden not in startup, forbidden
assert 'isReady(component)' in startup and 'defaults.set(complete, forKey:' in startup
content = (app / 'ContentView.swift').read_text()
gate = content[content.index('    private func launchLibraryEntry('):content.index('    private func launchPreparedLibraryEntry(')]
assert 'SteamClient.owns(entry)' in gate and 'steamPreparation.request(target: SteamClient.windowsExecutable' in gate
assert 'let resolved = SteamClient.entry(install: !SteamClient.installed, appID: entry.steamClientAppID)' in gate
assert 'steamPreparation.resolvedRoute(installer:' in gate
assert 'launchPreparedLibraryEntry(resolved, steamRequest: request)' in gate and 'TouchControlsHost.attach()' in gate
assert 'steamPreparation.permitsLaunch(steamRequest)' in content
assert '.fullScreenCover(isPresented: Binding(get: { steamPreparation.presented }' not in content
assert 'DeckSteamPreparationView()' in content
assert 'launch.beginPreparation()' in startup and 'DeckSteamLocalCovers.images()' in startup
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
        preconditionFailure("component queue did not finish")
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
        let target = "C:\\Program Files\\Steam Client\\steam.exe"
        func frame(_ image: String? = nil, visible: Bool = true, drawn: Bool = true,
                   width: Int = 640, height: Int = 480) -> DeckSteamFrame {
            DeckSteamFrame(image: image ?? target, width: width, height: height, visible: visible, drawn: drawn)
        }
        var preparation = fresh()
        let startup = DeckStartupModel(defaults: defaults)
        precondition(startup.phase == .chooseJIT)
        startup.choose(.automatic)
        precondition(startup.phase == .chooseJIT)
        MadeiraBuiltInJIT.isAvailable = false
        startup.choose(.builtIn)
        precondition(startup.phase == .chooseJIT)
        startup.choose(.externalScript)
        precondition(startup.phase == .ready && StartupFixture.calls.isEmpty)
        precondition(DeckStartupModel(defaults: defaults).phase == .ready)
        print("PASS: first JIT choice and returning app opens do not download components")

        var launch = DeckSteamLaunchPreparation(preparation: preparation)
        var requests: [UUID] = []
        launch.request(target: target, installer: false) { requests.append($0) }
        launch.request(target: target, installer: false) { requests.append($0) }
        precondition(launch.presented && launch.phase == .components && StartupFixture.calls.isEmpty)
        launch.beginPreparation(); launch.beginPreparation()
        precondition(StartupFixture.calls == DeckSetupComponent.allCases)
        precondition(StartupFixture.active.count == 3 && StartupFixture.peakDownloads == 3)
        launch.returnToLibrary()
        precondition(launch.presented)
        await wait(preparation)
        precondition(preparation.complete && launch.presented && launch.phase == .starting && requests.count == 1)
        let token = requests[0]
        precondition(launch.permitsLaunch(token))
        let began = Date()
        precondition(launch.sessionStarted(UUID(), at: began))
        precondition(launch.awaitingClientImage)
        precondition(launch.phase == .waitingForFrame && launch.presented && !launch.permitsLaunch(token))
        launch.waitingStageShown(at: began)
        for invalid in [
            frame("C:\\windows\\explorer.exe"), frame("C:\\windows\\system32\\conhost.exe"),
            frame("C:\\Program Files (x86)\\Steam\\steam.exe"), frame("C:\\other\\steam.exe"),
            frame(""), frame(visible: false), frame(drawn: false),
            frame(width: 1, height: 1), frame("C:\\Program Files\\Steam Client\\steamapps\\common\\x\\steamwebhelper.exe")
        ] {
            launch.observe([invalid], at: began)
            precondition(launch.presented && launch.phase == .waitingForFrame)
        }
        launch.observe([], at: began.addingTimeInterval(121))
        precondition(launch.presented && launch.phase == .waitingForFrame && launch.slow)
        launch.observe([frame()], at: began.addingTimeInterval(130))
        precondition(launch.presented && launch.phase == .waitingForFrame)
        launch.observe([frame()], at: began.addingTimeInterval(131))
        precondition(launch.presented && launch.phase == .revealing)
        precondition(!launch.awaitingClientImage)
        launch.observe([], at: began.addingTimeInterval(200))
        precondition(launch.presented && launch.phase == .revealing)
        launch.completeReveal(UUID())
        precondition(launch.presented)
        launch.completeReveal(launch.revealID!)
        precondition(!launch.presented && launch.phase == .idle)
        print("PASS: the layer survives long waits, reveals the actual target, and closes only after its fade completes")
        print("PASS: desktop, console, Dock's other Steam, unknown/hidden/undrawn/tiny and game windows cannot close it")

        precondition(DeckSteamFrameRules.accepts(frame("\\??\\C:\\PROGRAM FILES\\STEAM CLIENT\\STEAM.EXE"),
                                               target: target, installer: false))
        precondition(DeckSteamFrameRules.accepts(frame("C:\\Program Files\\Steam Client\\bin\\cef\\steamwebhelper.exe"),
                                               target: target, installer: false))
        let setup = "C:\\Madeira\\Installers\\SteamSetup.exe"
        precondition(DeckSteamFrameRules.accepts(frame(setup), target: setup, installer: true))
        precondition(!DeckSteamFrameRules.accepts(frame(), target: setup, installer: true))
        print("PASS: NT/case normalization, same-client CEF ownership and a separately identified installer frame")

        preparation = fresh()
        StartupFixture.failures = [.gecko]
        defaults.set(true, forKey: DeckStartupRules.completeKey)
        launch = DeckSteamLaunchPreparation(preparation: preparation)
        requests = []
        launch.request(target: target, installer: false) { requests.append($0) }
        launch.beginPreparation()
        await wait(preparation)
        precondition(launch.presented && launch.phase == .failed && requests.isEmpty)
        precondition(preparation.readyCount == 2 && !defaults.bool(forKey: DeckStartupRules.completeKey))
        StartupFixture.failures = []; StartupFixture.calls = []
        launch.retry()
        await wait(preparation)
        precondition(StartupFixture.calls == [.gecko] && launch.phase == .starting && requests.count == 1)
        let abandoned = requests[0]
        launch.returnToLibrary()
        precondition(!launch.presented && !launch.permitsLaunch(abandoned))
        requests = []
        launch.request(target: target, installer: false) { requests.append($0) }
        launch.beginPreparation()
        await wait(preparation)
        precondition(requests.count == 1 && requests[0] != abandoned && !launch.permitsLaunch(abandoned))
        precondition(launch.permitsLaunch(requests[0]))
        launch.fail("JIT cancelled")
        precondition(launch.presented && launch.phase == .failed && !launch.permitsLaunch(requests[0]))
        print("PASS: failed component retry, duplicate request suppression and abandoned/failed JIT continuations")

        launch.returnToLibrary()
        preparation = fresh()
        launch = DeckSteamLaunchPreparation(preparation: preparation)
        requests = []
        var clientAttempts = 0
        launch.request(target: target, installer: false, prepareClient: {
            clientAttempts += 1
            if clientAttempts == 1 { throw NSError(domain:"synthetic-client64",code:1) }
        }) { requests.append($0) }
        launch.beginPreparation(); await wait(preparation)
        try? await Task.sleep(nanoseconds: 40_000_000)
        precondition(launch.phase == .failed && requests.isEmpty && clientAttempts == 1)
        launch.retry(); await wait(preparation)
        try? await Task.sleep(nanoseconds: 40_000_000)
        precondition(launch.phase == .starting && requests.count == 1 && clientAttempts == 2)
        launch.returnToLibrary()
        var heldClient: CheckedContinuation<Void,Never>?
        requests = []
        launch.request(target: target, installer: false, prepareClient: {
            await withCheckedContinuation { heldClient = $0 }
            try Task.checkCancellation()
        }) { requests.append($0) }
        launch.beginPreparation(); await wait(preparation)
        try? await Task.sleep(nanoseconds: 40_000_000)
        precondition(launch.phase == .components && launch.setupMessage != nil && requests.isEmpty && heldClient != nil)
        launch.returnToLibrary()
        launch.request(target: target, installer: false) { requests.append($0) }
        launch.beginPreparation(); await wait(preparation)
        precondition(requests.count == 1)
        heldClient?.resume(); heldClient = nil
        try? await Task.sleep(nanoseconds: 40_000_000)
        precondition(requests.count == 1 && launch.phase == .starting)
        launch.returnToLibrary()
        print("PASS: Win64 client preparation stays under the download overlay; failure retries and cancelled/stale downloads cannot launch Wine")

        preparation = fresh()
        WineMonoModel.available = true; WineGeckoModel.available = true
        var joined = 0
        preparation.prepare { if $0 { joined += 1 } }
        launch = DeckSteamLaunchPreparation(preparation: preparation)
        requests = []
        launch.request(target: target, installer: false) { requests.append($0) }
        launch.beginPreparation()
        await wait(preparation)
        precondition(StartupFixture.calls == [.visualCPP] && joined == 1 && requests.count == 1)
        precondition(launch.sessionStarted(UUID()))
        launch.sessionEnded("Wine stopped before frame")
        precondition(launch.presented && launch.phase == .failed && launch.error == "Wine stopped before frame")
        launch.returnToLibrary()
        precondition(!launch.presented)
        print("PASS: shared existing downloads and a session ending before the first frame stay distinct from success")

        preparation = fresh()
        StartupFixture.sessionRunning = true
        launch = DeckSteamLaunchPreparation(preparation: preparation)
        launch.request(target: target, installer: false) { _ in preconditionFailure("active Wine launched") }
        launch.beginPreparation()
        precondition(!preparation.running && launch.phase == .failed && StartupFixture.calls.isEmpty)
        preparation = fresh()
        MadeiraDock.bundled = false; MadeiraDock.clientInstalled = true
        preparation.prepare()
        await wait(preparation)
        precondition(preparation.complete && preparation.readyCount == 3 && StartupFixture.calls == [.mono, .visualCPP, .gecko])
        print("PASS: active Wine sessions cannot prepare; missing Dock never blocks the three required components")

        preparation = fresh()
        WineMonoModel.available = true; WineGeckoModel.available = true
        VCRedistModel.shared.complete = true; MadeiraDock.clientInstalled = true
        launch = DeckSteamLaunchPreparation(preparation: preparation)
        launch.request(target: target, installer: false) { _ in }
        launch.beginPreparation()
        await wait(preparation)
        precondition(StartupFixture.calls.isEmpty && launch.phase == .starting && launch.presented)
        precondition(launch.sessionStarted(UUID()))
        launch.closeRequested()
        precondition(launch.closing && launch.presented && launch.phase == .failed)
        launch.sessionEnded(nil)
        precondition(!launch.presented)
        WineGeckoModel.available = false
        launch.request(target: target, installer: false) { _ in }
        launch.beginPreparation()
        await wait(preparation)
        precondition(StartupFixture.calls == [.gecko])
        print("PASS: cached components still use the animation, explicit close completes safely, and missing files recheck")

        let fast = Date()
        precondition(launch.sessionStarted(UUID(), at: fast))
        launch.observe([frame()], at: fast.addingTimeInterval(10))
        precondition(launch.phase == .waitingForFrame)
        // JIT suspended rendering for ten seconds; count visible waiting time
        // from the view's arrival, not from sessionStarted.
        launch.waitingStageShown(at: fast.addingTimeInterval(10))
        launch.observe([frame()], at: fast.addingTimeInterval(10.1))
        precondition(launch.phase == .waitingForFrame)
        launch.waitingStageShown(at: fast.addingTimeInterval(10.5))
        launch.observe([frame(drawn: false)], at: fast.addingTimeInterval(11))
        precondition(launch.phase == .waitingForFrame)
        launch.observe([frame()], at: fast.addingTimeInterval(11))
        precondition(launch.phase == .revealing && launch.presented)
        let staleReveal = launch.revealID!
        launch.sessionEnded("Steam exited during fade")
        launch.completeReveal(staleReveal)
        precondition(launch.presented && launch.phase == .failed)
        launch.returnToLibrary()
        launch.request(target: target, installer: false) { _ in }
        launch.completeReveal(staleReveal)
        precondition(launch.presented && launch.phase == .components)
        print("PASS: fast frames cannot skip the visible waiting stage; interrupted and stale fades cannot dismiss another state")

        preparation = fresh()
        launch = DeckSteamLaunchPreparation(preparation: preparation)
        launch.request(target: target, installer: false) { _ in }
        launch.beginPreparation(); await wait(preparation)
        launch.resolvedRoute(installer: true)
        precondition(launch.sessionStarted(UUID(), at: fast) && launch.phase == .installing)
        launch.observe([frame(setup)], at: fast.addingTimeInterval(20))
        launch.observe([frame()], at: fast.addingTimeInterval(21))
        precondition(launch.presented && launch.phase == .installing)
        func status(_ stage: String, code: UInt32 = 0, step: Int = 4, percent: Int = -1, blocked: Int = 0) -> DeckSteamSetupStatus {
            DeckSteamSetupStatus.decode("v1\nstage=\(stage)\nerror=\(code)\n", step:step, percent:percent, blocked:blocked)!
        }
        launch.observeSetup(status("installer",percent:42))
        precondition(launch.setupFraction == 0.42 && launch.phase == .installing)
        launch.observeSetup(status("checking"))
        precondition(launch.presented && launch.phase == .installing && launch.setupFraction == nil)
        launch.observeSetup(status("starting"))
        precondition(launch.phase == .installing)
        launch.observeSetup(status("waiting"),at:fast.addingTimeInterval(25))
        precondition(launch.phase == .waitingForFrame && !launch.installer)
        launch.waitingStageShown(at:fast.addingTimeInterval(25))
        launch.observe([frame(setup)],at:fast.addingTimeInterval(26))
        precondition(launch.phase == .waitingForFrame)
        launch.observe([frame()],at:fast.addingTimeInterval(27))
        launch.observe([frame()],at:fast.addingTimeInterval(28))
        precondition(launch.phase == .revealing)
        launch.completeReveal(launch.revealID!)
        precondition(!launch.presented)
        for corrupt in ["", "v1\nstage=checking\nerror=2\n", "v1\nstage=other\nerror=0\n", "v1\nstage=waiting\nerror=0"] {
            precondition(DeckSteamSetupStatus.decode(corrupt,step:0,percent:0,blocked:0) == nil)
        }
        launch.request(target:target,installer:true){_ in};launch.beginPreparation();await wait(preparation)
        precondition(launch.sessionStarted(UUID()))
        launch.observeSetup(status("failed",code:2))
        precondition(launch.phase == .failed && launch.presented)
        launch.observeSetup(status("waiting"))
        precondition(launch.phase == .failed)
        launch.sessionEnded(nil); launch.returnToLibrary()
        launch.request(target:target,installer:true){_ in};launch.beginPreparation();await wait(preparation)
        precondition(launch.sessionStarted(UUID()))
        launch.observeSetup(status("installer",blocked:2))
        precondition(launch.phase == .failed && launch.presented)
        launch.sessionEnded(nil); launch.returnToLibrary()
        launch.request(target:target,installer:true){_ in};launch.beginPreparation();await wait(preparation)
        precondition(launch.sessionStarted(UUID()))
        launch.observeSetup(status("installer",blocked:4))
        precondition(launch.phase == .failed && launch.presented && launch.error?.contains("dialog") == true)
        print("PASS: setup/desktop/early client frames stay covered; only post-exit launch plus Steam's actual image completes; failures do not reveal")
        launch.sessionEnded(nil); launch.returnToLibrary()
        let browserSession = UUID()
        launch.runtimeFailure("synthetic CEF address failure", session: browserSession)
        precondition(launch.presented && launch.phase == .failed && launch.error == "synthetic CEF address failure")
        precondition(!launch.canRetry)
        launch.observe([frame()], at: fast.addingTimeInterval(1000))
        precondition(launch.phase == .failed)
        launch.runtimeFailure("old-session message", session: UUID())
        precondition(launch.error == "synthetic CEF address failure")
        launch.closeRequested()
        launch.runtimeFailure("late failure", session: browserSession)
        precondition(launch.closing && launch.error == "Closing the Steam session…")
        launch.sessionEnded(nil)
        precondition(!launch.presented)
        print("PASS: a post-reveal CEF failure opens an error layer, ignores other sessions/late frames and preserves explicit close")
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
        sampler = library[library.index('@MainActor enum DeckSteamLocalCovers {'):library.index('\nstruct LibraryView: View {')]
        sampler_file = folder / 'NativeFrames.swift'
        sampler_file.write_text('import SwiftUI\nimport UIKit\nimport ImageIO\n' + sampler)
        ios_fixture = folder / 'IOSDependencies.swift'
        ios_fixture.write_text(fixture.read_text().replace('enum DeckSteamLocalCovers { @MainActor static func images() -> [Image] { [] } }', ''))
        bridge = folder / 'NativeBridge.h'
        bridge.write_text('#include "'+str(app / 'Winios/Winios.h')+'"\n#include "'+str(app / 'JITAllocator.h')+'"\n')
        subprocess.run(['xcrun', 'swiftc', '-typecheck', '-sdk', sdk, '-target', 'arm64-apple-ios18.0',
                        '-import-objc-header', str(bridge),
                        str(app / 'DeckStartup.swift'), str(app / 'DeckDesign.swift'), str(method_file), str(ios_fixture),
                        str(app / 'DeckSteamLoading.swift'), str(app / 'AppEntryJIT.swift'), str(sampler_file)], check=True)
        print('PASS: native loading views, actual window-census C bridge, startup and AVPlayer typechecked against iOS SDK')
print('No IPA build, network download, signing, installation or physical-device test performed.')
