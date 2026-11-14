#!/usr/bin/env python3
"""Front end Settings: display rate, swap tier and the sync engine.

1. Swift: compiles the production MadeiraConfig (app/Madeira/MadeiraConfig.swift)
   with HOME pointed at a scratch directory and checks MadeiraConfig.set():
   it keeps comments and other keys, replaces earlier lines for the key,
   removes a key for nil, migrates legacy madeira-*.txt files before creating
   madeira.cfg, and MadeiraConfig.flag() reads env.NAME lines. With the
   production SyncEngine (Library.swift): no key is Fastsync (the default);
   Fastsync removes both keys; Madsync writes inproc-sync = 1 and removes
   env.MADEIRA_FASTSYNC; Wine standard sync writes inproc-sync = 0 and removes
   env.MADEIRA_FASTSYNC; a hand-edited madeira.cfg reads back as the engine
   Wine will run (madsync wins over any MADEIRA_FASTSYNC value).
2. Source checks on app/Madeira/Library.swift and FPSOverlay.swift: the
   mdeck defaults are the selected memory values, Fastsync and display-rate hold off, the
   Sync engine picker writes through SyncEngine.apply, game details offer the
   Fastsync-only switches greyed out unless Fastsync is chosen, launches export
   them only with Fastsync, and MADEIRA_RUNTIME_SETTINGS=0 hides both sections.

Run from anywhere; needs `swift` on PATH.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
config = (root / 'app/Madeira/MadeiraConfig.swift').read_text()
lib = (root / 'app/Madeira/Library.swift').read_text()
fps = (root / 'app/Madeira/FPSOverlay.swift').read_text()
failures = []


def block(text, header):
    p = text.index(header)
    a = text.index('{', p)
    n, b = 1, a + 1
    while n:
        n += (text[b] == '{') - (text[b] == '}')
        b += 1
    return text[p:b]


def check(cond, what):
    print(('PASS: ' if cond else 'FAIL: ') + what)
    if not cond:
        failures.append(what)


swift = config + '\nfunc L(_ text: String) -> String { text }   // Library.swift\'s lookup; English here\n' + block(lib,'enum SyncEngine: String, CaseIterable, Identifiable') + r'''
var failed = 0
func expect(_ cond: Bool, _ what: String) { print((cond ? "PASS: " : "FAIL: ") + what); if !cond { failed += 1 } }
let docs = MadeiraConfig.documents!
try? FileManager.default.createDirectory(at: docs, withIntermediateDirectories: true)
let cfg = docs.appendingPathComponent("madeira.cfg")

// No madeira.cfg, one legacy file: set() migrates it first, so it is not hidden.
try! "2048\n".write(to: docs.appendingPathComponent("madeira-vram-mb.txt"), atomically: true, encoding: .utf8)
expect(!MadeiraConfig.present, "no madeira.cfg at the start")
expect(MadeiraConfig.set("swap-mb", "1024"), "set() creates madeira.cfg")
expect(MadeiraConfig.get("vram-mb") == "2048" && MadeiraConfig.get("swap-mb") == "1024", "legacy value migrated, new key written")

// Comments and other keys survive; the key's earlier lines are replaced.
try! "# my notes\nswap-mb = 4096\nwx = 1\nswap-mb=2048\nenv.MADEIRA_PROMOTE = 0\n".write(to: cfg, atomically: true, encoding: .utf8)
MadeiraConfig.set("swap-mb", "1024")
let text = try! String(contentsOf: cfg, encoding: .utf8)
expect(text.contains("# my notes") && text.contains("wx = 1"), "comments and other keys are kept")
expect(text.components(separatedBy: "swap-mb").count == 2 && MadeiraConfig.get("swap-mb") == "1024", "one line for the key, new value")
expect(!MadeiraConfig.flag("MADEIRA_PROMOTE", fallback: false), "env.MADEIRA_PROMOTE = 0 reads as off")
MadeiraConfig.set("env.MADEIRA_PROMOTE", "1")
expect(MadeiraConfig.flag("MADEIRA_PROMOTE", fallback: false), "env.MADEIRA_PROMOTE = 1 reads as on")
MadeiraConfig.set("env.MADEIRA_PROMOTE", nil)
expect(!MadeiraConfig.flag("MADEIRA_PROMOTE", fallback: false), "removed key: the fallback (off)")
expect(MadeiraConfig.flag("MADEIRA_SOMETHING_ELSE"), "unset flags use their fallback (on)")
MadeiraConfig.set("inproc-sync", "0")
expect(!MadeiraConfig.bool("inproc-sync", default: true), "madsync off is inproc-sync = 0")
MadeiraConfig.set("inproc-sync", nil)
expect(MadeiraConfig.bool("inproc-sync", default: true), "a removed key reads as the default")

// Sync engine: exactly one engine, and the keys Wine reads for it.
expect(SyncEngine.current == .fastsync, "no sync keys: Fastsync (the default)")
SyncEngine.apply(.madsync)
SyncEngine.apply(.fastsync)
expect(MadeiraConfig.get("inproc-sync") == nil && MadeiraConfig.get("env.MADEIRA_FASTSYNC") == nil
       && SyncEngine.current == .fastsync, "Fastsync: both keys removed (the default)")
SyncEngine.apply(.wine)
expect(MadeiraConfig.get("inproc-sync") == "0" && MadeiraConfig.get("env.MADEIRA_FASTSYNC") == nil
       && SyncEngine.current == .wine, "Wine standard sync: inproc-sync = 0, no MADEIRA_FASTSYNC")
SyncEngine.apply(.madsync)
expect(MadeiraConfig.get("inproc-sync") == "1" && MadeiraConfig.get("env.MADEIRA_FASTSYNC") == nil
       && SyncEngine.current == .madsync, "Madsync: inproc-sync = 1, no MADEIRA_FASTSYNC")
let kept = try! String(contentsOf: cfg, encoding: .utf8)
expect(kept.contains("# my notes") && kept.contains("wx = 1"), "engine changes keep comments and other keys")
MadeiraConfig.set("env.MADEIRA_FASTSYNC", "1")
expect(SyncEngine.current == .madsync, "hand-edited: madsync on wins over MADEIRA_FASTSYNC (Wine runs madsync)")
MadeiraConfig.set("inproc-sync", "0")
expect(SyncEngine.current == .fastsync, "hand-edited: inproc-sync = 0 with MADEIRA_FASTSYNC = 1 is Fastsync")
MadeiraConfig.set("env.MADEIRA_FASTSYNC", "0")
expect(SyncEngine.current == .wine, "hand-edited: MADEIRA_FASTSYNC = 0 without madsync is Wine standard sync")
MadeiraConfig.set("env.MADEIRA_FASTSYNC", nil)
expect(SyncEngine.current == .wine, "inproc-sync = 0 without MADEIRA_FASTSYNC stays Wine standard sync (as written before)")
MadeiraConfig.set("inproc-sync", nil)
expect(SyncEngine.current == .fastsync, "neither key: Fastsync")

// The screenshot's selections are seeded before the first UI/runtime read.
let fresh = docs.appendingPathComponent("new-defaults/madeira.cfg")
expect(MadeiraConfig.installMdeckRuntimeDefaults(at: fresh), "fresh install writes mdeck runtime defaults")
let freshText = try! String(contentsOf: fresh, encoding: .utf8)
let values = MadeiraConfig.parse(freshText)
expect(values == ["pool":"1152", "swap-mb":"4096", "env.MADEIRA_SWAP_COVERAGE":"classic", "donor-pool-mb":"6144"],
       "1152 MB JIT, auto VRAM, 4 GB swap, large allocations, 6 GB donor, donor-only WOW, Fastsync and eco off")
expect(!MadeiraConfig.installMdeckRuntimeDefaults(at: fresh), "defaults are installed once")
expect(MadeiraConfig.installPerformanceLogDefaults(at: fresh), "new performance logging switch defaults to off")
let quiet = MadeiraConfig.parse(try! String(contentsOf: fresh, encoding: .utf8))
expect(quiet["env.MADEIRA_PROBES"] == "0" && quiet["env.MADEIRA_FRAME_STATS"] == "0" && quiet["pool"] == "1152",
       "performance defaults disable samplers without changing runtime memory settings")
let original = "# keep notes\npool = 896\nenv.WINEDEBUG = trace+process\nenv.MADEIRA_PROBES = 1\nenv.MADEIRA_PROBES=0\n"
let profiling = PerformanceLogSettings.text(original, enabled: true)
expect(PerformanceLogSettings.enabled(global: quiet, profile: profiling), "profile overrides global defaults with the lightweight preset")
expect(PerformanceLogSettings.enabled(global: quiet, profile: "env.MADEIRA_PROBES = 1\n"), "an existing full manual profiler is shown as enabled")
expect(PerformanceLogSettings.enabled(global: quiet, profile: "env.MADEIRA_FRAME_STATS = 1\n"), "an existing frame-only preset is shown as enabled")
expect(profiling.contains("# keep notes") && profiling.contains("pool = 896") && profiling.contains("env.WINEDEBUG = trace+process"),
       "the switch preserves comments, memory settings and separate Wine logging choices")
expect(profiling.components(separatedBy: "env.MADEIRA_PROBES").count == 2, "switch removes duplicate preset keys")
let off = PerformanceLogSettings.text(profiling, enabled: false)
expect(!PerformanceLogSettings.enabled(global: quiet, profile: off) && MadeiraConfig.parse(off)["env.MADEIRA_PROBES"] == "0"
       && MadeiraConfig.parse(off)["env.MADEIRA_FRAME_STATS"] == "0", "off stops the preset's counters and frame logging")
expect(PerformanceLogSettings.text(profiling, enabled: true) == profiling, "repeated enabling is idempotent")
expect(!SteamSurfaceLogSettings.enabled(global: [:], profile: ""), "Steam surface diagnostics default off")
let steamSurface = SteamSurfaceLogSettings.text(profiling, enabled: true)
expect(SteamSurfaceLogSettings.enabled(global: [:], profile: steamSurface), "Steam surface diagnostics can be enabled independently")
expect(PerformanceLogSettings.enabled(global: quiet, profile: steamSurface), "surface diagnostics preserve the CPU performance preset")
expect(SteamSurfaceLogSettings.text(steamSurface, enabled: true) == steamSurface, "surface diagnostics enabling is idempotent")
let noCPU = PerformanceLogSettings.text(steamSurface, enabled: false)
expect(SteamSurfaceLogSettings.enabled(global: quiet, profile: noCPU)
       && !PerformanceLogSettings.enabled(global: quiet, profile: noCPU), "turning CPU sampling off preserves Steam diagnostics")
let noSurface = SteamSurfaceLogSettings.text(steamSurface, enabled: false)
expect(!SteamSurfaceLogSettings.enabled(global: [SteamSurfaceLogSettings.key: "1"], profile: noSurface)
       && PerformanceLogSettings.enabled(global: quiet, profile: noSurface), "profile off overrides global on without disabling CPU logs")
let duplicates = "# keep me\npool=1152\nenv.MADEIRA_STEAM_SURFACE_STATS = 1\nenv.MADEIRA_STEAM_SURFACE_STATS=0\n"
let deduped = SteamSurfaceLogSettings.text(duplicates, enabled: true)
expect(deduped.components(separatedBy: SteamSurfaceLogSettings.key).count == 2
       && deduped.contains("# keep me") && deduped.contains("pool=1152"), "surface switch removes duplicate keys while keeping notes and unrelated settings")
expect(!SteamAllocationLogSettings.enabled(global: [:], profile: steamSurface), "existing window diagnostics do not enable allocation timing")
expect(!SteamHotspotSettings.enabled(global: [:], profile: steamSurface), "CEF hotspot capture defaults off even with window diagnostics")
for cpuEnabled in [false, true] {
    for windowEnabled in [false, true] {
        for allocationEnabled in [false, true] {
            var independent = PerformanceLogSettings.text(original, enabled: cpuEnabled)
            independent = SteamSurfaceLogSettings.text(independent, enabled: windowEnabled)
            independent = SteamAllocationLogSettings.text(independent, enabled: allocationEnabled)
            expect(PerformanceLogSettings.enabled(global: quiet, profile: independent) == cpuEnabled
                   && SteamSurfaceLogSettings.enabled(global: [:], profile: independent) == windowEnabled
                   && SteamAllocationLogSettings.enabled(global: [:], profile: independent) == allocationEnabled,
                   "CPU, window and allocation switches retain independent values: \(cpuEnabled)/\(windowEnabled)/\(allocationEnabled)")
            expect(SteamAllocationLogSettings.text(independent, enabled: allocationEnabled) == independent,
                   "allocation switch writes are idempotent")
            for hotspotEnabled in [false, true] {
                let capture = SteamHotspotSettings.text(independent, enabled: hotspotEnabled)
                expect(SteamHotspotSettings.enabled(global: [:], profile: capture) == hotspotEnabled
                       && PerformanceLogSettings.enabled(global: quiet, profile: capture) == cpuEnabled
                       && SteamSurfaceLogSettings.enabled(global: [:], profile: capture) == windowEnabled
                       && SteamAllocationLogSettings.enabled(global: [:], profile: capture) == allocationEnabled,
                       "hotspot switch is independent: \(cpuEnabled)/\(windowEnabled)/\(allocationEnabled)/\(hotspotEnabled)")
                expect(SteamHotspotSettings.text(capture, enabled: hotspotEnabled) == capture, "hotspot writes are idempotent")
            }
        }
    }
}
let allocationDuplicates = "# keep me\npool=1152\nenv.MADEIRA_STEAM_ALLOC_STATS = 1\nenv.MADEIRA_STEAM_ALLOC_STATS=0\n"
let allocationOff = SteamAllocationLogSettings.text(allocationDuplicates, enabled: false)
expect(allocationOff.components(separatedBy: SteamAllocationLogSettings.key).count == 2
       && allocationOff.contains("# keep me") && allocationOff.contains("pool=1152")
       && !SteamAllocationLogSettings.enabled(global: [SteamAllocationLogSettings.key: "1"], profile: allocationOff),
       "allocation switch deduplicates its own key, preserves unrelated settings and overrides global on")
expect(!SteamCompileReasonSettings.enabled(global: [:], profile: ""), "compilation reason logging defaults off")
let reasonOn = SteamCompileReasonSettings.text("# keep\npool=1152\nenv.MADEIRA_STEAM_COMPILE_REASONS=0\nenv.MADEIRA_STEAM_COMPILE_REASONS=1\n", enabled: true)
expect(SteamCompileReasonSettings.enabled(global: [:], profile: reasonOn)
       && reasonOn.components(separatedBy: SteamCompileReasonSettings.key).count == 2
       && reasonOn.contains("# keep") && reasonOn.contains("pool=1152"), "compilation log key deduplicates and preserves unrelated options")
expect(SteamCompileReasonSettings.text(reasonOn, enabled: true) == reasonOn, "compilation logging writes are idempotent")
expect(!SteamCompileReasonSettings.enabled(global: [SteamCompileReasonSettings.key:"1"], profile: SteamCompileReasonSettings.text(reasonOn, enabled: false)), "compilation logging profile off overrides global")
expect(!SteamHotspotSettings.enabled(global: [:], profile: reasonOn)
       && !SteamAllocationLogSettings.enabled(global: [:], profile: reasonOn)
       && !SteamSurfaceLogSettings.enabled(global: [:], profile: reasonOn), "compile reason logging is independent of hotspot/window/allocation switches")
expect(SteamCompileReasonSettings.enabled(global: [SteamCompileReasonSettings.key:"1"], profile:""), "global compilation logging is inherited")
expect(!SteamCompileReasonSettings.enabled(global: [SteamCompileReasonSettings.key:"true"], profile:""), "compilation logger accepts exact 1 only")
expect(SteamDFEScratchSettings.enabled(global: [:], profile: ""), "DFE reuse defaults on")
let dfeOff = SteamDFEScratchSettings.text("# preserve\npool=1152\nenv.MADEIRA_FEX_DFE_REUSE=1\nenv.MADEIRA_FEX_DFE_REUSE=0\n", enabled: false)
expect(!SteamDFEScratchSettings.enabled(global: [SteamDFEScratchSettings.key:"1"], profile: dfeOff)
       && dfeOff.components(separatedBy: SteamDFEScratchSettings.key).count == 2
       && dfeOff.contains("# preserve") && dfeOff.contains("pool=1152"), "DFE profile off wins, preserves settings and deduplicates")
expect(SteamDFEScratchSettings.text(dfeOff, enabled: false) == dfeOff, "DFE setting is idempotent")
expect(!SteamDFEScratchSettings.enabled(global: [SteamDFEScratchSettings.key:"0"], profile:""), "DFE global off is inherited")
expect(SteamDFEScratchSettings.enabled(global: [SteamDFEScratchSettings.key:"0"], profile:SteamDFEScratchSettings.text(dfeOff, enabled:true)), "DFE profile on overrides global off")
for value in ["", "1", "true", "00", "false"] {
    expect(SteamDFEScratchSettings.enabled(global: [SteamDFEScratchSettings.key:value], profile:""), "DFE runtime and UI disable only for exact zero")
}
for reuse in [false,true] { for logging in [false,true] {
    let combination = SteamCompileReasonSettings.text(SteamDFEScratchSettings.text("", enabled:reuse), enabled:logging)
    expect(SteamDFEScratchSettings.enabled(global:[:],profile:combination)==reuse
           && SteamCompileReasonSettings.enabled(global:[:],profile:combination)==logging
           && !SteamCacheLookupSettings.enabled(global:[:],profile:combination), "DFE, RA capture and L1 choices are independent")
} }
expect(!SteamCacheLookupSettings.enabled(global: [:], profile: ""), "cache indexing experiment defaults off")
let lookupOn = SteamCacheLookupSettings.text("# preserve\npool=1152\nenv.MADEIRA_FEX_L1_HASH=0\nenv.MADEIRA_FEX_L1_HASH=1\n", enabled: true)
expect(SteamCacheLookupSettings.enabled(global: [:], profile: lookupOn)
       && lookupOn.components(separatedBy: SteamCacheLookupSettings.key).count == 2
       && lookupOn.contains("# preserve") && lookupOn.contains("pool=1152"), "cache lookup toggle deduplicates and preserves profile")
expect(SteamCacheLookupSettings.text(lookupOn, enabled: true) == lookupOn, "cache lookup toggle is idempotent")
let lookupOff = SteamCacheLookupSettings.text(lookupOn, enabled: false)
expect(!SteamCacheLookupSettings.enabled(global: [SteamCacheLookupSettings.key: "1"], profile: lookupOff), "profile off overrides global cache lookup on")
expect(SteamCacheLookupSettings.enabled(global: [SteamCacheLookupSettings.key: "1"], profile: ""), "cache lookup global setting is inherited")
for invalid in ["", "true", "2", "1junk"] {
    expect(!SteamCacheLookupSettings.enabled(global: [SteamCacheLookupSettings.key: invalid], profile: ""), "cache lookup only accepts runtime-compatible 1: \(invalid)")
}
expect(!SteamHotspotSettings.enabled(global: [:], profile: lookupOn)
       && !SteamAllocationLogSettings.enabled(global: [:], profile: lookupOn)
       && !SteamSurfaceLogSettings.enabled(global: [:], profile: lookupOn), "cache optimization does not enable diagnostics")
let hotspotOff = SteamHotspotSettings.text("# preserve\npool=1152\nenv.MADEIRA_STEAM_HOTSPOT=1\nenv.MADEIRA_STEAM_HOTSPOT=0\n", enabled: false)
expect(hotspotOff.components(separatedBy: SteamHotspotSettings.key).count == 2
       && hotspotOff.contains("# preserve") && hotspotOff.contains("pool=1152")
       && !SteamHotspotSettings.enabled(global: [SteamHotspotSettings.key: "1"], profile: hotspotOff),
       "hotspot key deduplicates, preserves unrelated settings and profile off overrides global on")
try! profiling.write(to: fresh, atomically: true, encoding: .utf8)
expect(!MadeiraConfig.installPerformanceLogDefaults(at: fresh) && (try! String(contentsOf: fresh, encoding: .utf8)) == profiling,
       "upgrade preserves manually selected performance logging")
let upgraded = docs.appendingPathComponent("upgrade-defaults/madeira.cfg")
try! FileManager.default.createDirectory(at: upgraded.deletingLastPathComponent(), withIntermediateDirectories: true)
let oldGlobal = "# keep my notes\npool = 512\npool = 896\nvram-mb = 2048\nswap-mb = 2048\nswap-min-mb = 1\nswap-min-kb = 64\nswap-mode = 2\nenv.MADEIRA_SWAP_MIN_KB = 64\nenv.MADEIRA_SWAP_COVERAGE = broad\ndonor-pool-mb = 4096\nswap-wow64 = 1\ninproc-sync = 1\nenv.MADEIRA_FASTSYNC = 0\neco = 1\nd3d9 = wined3d\nenv.CUSTOM = keep\n"
try! oldGlobal.write(to: upgraded, atomically: true, encoding: .utf8)
expect(MadeiraConfig.installMdeckRuntimeDefaults(at: upgraded), "old install receives selected defaults once")
let upgradedText = try! String(contentsOf: upgraded, encoding: .utf8)
let upgradedValues = MadeiraConfig.parse(upgradedText)
expect(upgradedValues == values.merging(["d3d9":"wined3d", "env.CUSTOM":"keep"]) { $1 } && upgradedText.contains("# keep my notes"),
       "stale coverage, thresholds, VRAM, WOW and sync overrides are removed; unrelated keys and comments survive")
let backup = upgraded.appendingPathExtension("before-mdeck-defaults-v1.bak")
let backupText = try! String(contentsOf: backup, encoding: .utf8)
expect(backupText == oldGlobal, "original global config has a backup")
let later = upgradedText + "pool = 768\nswap-mb = 0\n"
try! later.write(to: upgraded, atomically: true, encoding: .utf8)
expect(!MadeiraConfig.installMdeckRuntimeDefaults(at: upgraded), "user can change the new defaults afterward")
expect((try! String(contentsOf: upgraded, encoding: .utf8)) == later, "app restart preserves later custom settings")
let blocked = docs.appendingPathComponent("blocked-defaults")
try! FileManager.default.createDirectory(at: blocked, withIntermediateDirectories: true)
expect(!MadeiraConfig.installMdeckRuntimeDefaults(at: blocked), "unreadable destination is not overwritten or marked complete")
try! FileManager.default.removeItem(at: blocked)
expect(MadeiraConfig.installMdeckRuntimeDefaults(at: blocked), "failed installation retries successfully")
exit(failed == 0 ? 0 : 1)
'''

with tempfile.TemporaryDirectory() as tmp:
    sp = Path(tmp) / 'settings.swift'
    sp.write_text(swift)
    home = Path(tmp) / 'home'
    home.mkdir()
    env = dict(os.environ, HOME=str(home), CFFIXED_USER_HOME=str(home))
    r = subprocess.run(['swift', str(sp)], capture_output=True, text=True, env=env)
    sys.stdout.write(r.stdout)
    if r.returncode:
        sys.stdout.write(r.stderr[-4000:])
        failures.append('swift harness')

settings = lib[lib.index('struct RuntimeMemorySyncSettings: View'):lib.index('struct LibraryPointerSettings: View')]
display = lib[lib.index('struct DisplayRateSettings: View'):lib.index('struct RuntimeMemorySyncSettings: View')]
engine = block(lib, 'enum SyncEngine: String, CaseIterable, Identifiable')
detail = lib[lib.index('struct LibraryDetail: View'):lib.index('struct RuntimeMemorySyncSettings: View')]
check('Toggle("Performance logging"' in detail and 'PerformanceLogSettings.enabled(global: MadeiraConfig.all(), profile: bcd.configText)' in detail
      and 'PerformanceLogSettings.text(file.text, enabled: enabled)' in detail
      and '.accessibilityIdentifier("steam-performance-logging")' in detail,
      'Steam advanced settings read and persist the standalone performance preset')
check('Toggle("Steam performance diagnostics"' in detail
      and 'SteamSurfaceLogSettings.enabled(global: MadeiraConfig.all(), profile: bcd.configText)' in detail
      and 'SteamSurfaceLogSettings.text(file.text, enabled: enabled)' in detail
      and '.accessibilityIdentifier("steam-surface-performance-logging")' in detail,
      'Steam advanced settings expose independent surface diagnostics')
check('Toggle("Steam allocation and retry diagnostics"' in detail
      and 'SteamAllocationLogSettings.enabled(global: MadeiraConfig.all(), profile: bcd.configText)' in detail
      and 'SteamAllocationLogSettings.text(file.text, enabled: enabled)' in detail
      and '.accessibilityIdentifier("steam-allocation-performance-logging")' in detail,
      'Steam advanced settings expose independent allocation/retry diagnostics')
check('Toggle("CEF hotspot capture"' in detail and 'SteamHotspotSettings.text(file.text, enabled: enabled)' in detail
      and '.accessibilityIdentifier("steam-cef-hotspot-capture")' in detail
      and 'Button("Stop CEF hotspot capture") { winios_hotspot_stop() }' in detail,
      'Steam advanced settings expose finite hotspot capture and a manual stop action')
app_source = (root / 'app/Madeira/MadeiraApp.swift').read_text()
check(app_source.index('MadeiraConfig.installMdeckRuntimeDefaults()') < app_source.index('MadeiraConfig.installPerformanceLogDefaults()')
      < app_source.index('SteamClientSignInSync.shared.start()'), 'sampling defaults initialize before runtime startup')
apply_env = block(lib, 'func applyEnvironment()')
entry = block(lib, 'struct LibraryEntry: Codable, Identifiable')
check('return inproc == nil ? .fastsync : .wine' in engine, 'fastsync is the engine unless madeira.cfg says otherwise')
check('@State private var engine = SyncEngine.current' in settings and 'Picker("Sync engine"' in settings
      and 'SyncEngine.apply(choice)' in settings and 'ForEach(SyncEngine.allCases)' in settings,
      'Settings: the Sync engine picker writes through SyncEngine.apply')
check(['Madsync', 'Fastsync (default)', 'Wine standard sync'] == re.findall(r'case \.\w+: return (?:L\()?"([^"]+)"', engine),
      'the picker offers Madsync, Fastsync (default) and Wine standard sync, in that order')
check('"env.MADEIRA_FASTSYNC"' in settings.split('static let featuredKeys')[1].split(']')[0],
      'All settings leaves env.MADEIRA_FASTSYNC to the picker')
check('var fastSync: Bool?' in entry and 'var semaphoreFastPath: Bool?' in entry,
      'per-game fastsync switches are optional, so older library files decode')
check('Toggle("Fast synchronization"' in detail and 'Toggle("Fast semaphore waits (experimental)"' in detail
      and '.disabled(syncEngine != .fastsync)' in detail and '@State private var syncEngine = SyncEngine.current' in detail,
      'game details: Fast synchronization and Fast semaphore waits, greyed out unless the engine is Fastsync')
check('if syncEngine != .fastsync {' in detail and 'Choose Fastsync in Settings' in detail,
      'game details: a note says where to choose Fastsync')
check('if SyncEngine.current == .fastsync {' in apply_env and 'setenv("MADEIRA_FASTSYNC", fastSync == false ? "0" : mode, 1)' in apply_env
      and 'if let sem = semaphoreFastPath { setenv("MADEIRA_FASTSYNC_SEM", sem ? "1" : "0", 1) }' in apply_env
      and 'else { unsetenv("MADEIRA_FASTSYNC_SEM") }' in apply_env,
      'a launch exports the fastsync switches only when the engine is Fastsync')
check('static let swapChoices = [0, 1024, 2048, 3072, 4096]' in settings and 'mb > 0 ? String(mb) : nil' in settings,
      'swap tier: Off removes swap-mb after the initial 4 GB seed')
startup = (root / 'app/Madeira/MadeiraApp.swift').read_text()
check(startup.index('MadeiraConfig.installMdeckRuntimeDefaults()') < startup.index('SteamOwnedLibrary.shared.start()'),
      'selected runtime defaults are installed before frontend and library startup')
check('@State private var hold = ProMotionIntent.holdMaximum' in display
      and 'MadeiraConfig.set("env.MADEIRA_PROMOTE", on ? "1" : nil)' in display, 'display-rate hold writes env.MADEIRA_PROMOTE')
check('static var holdMaximum: Bool { MadeiraConfig.flag("MADEIRA_PROMOTE", fallback: false) }' in fps,
      'display-rate hold is off by default')
# Both sections sit inside the one MADEIRA_RUNTIME_SETTINGS block (each is also
# wrapped in the Settings search filter, settingsShow(...), since main d5a8e0a).
_rt = lib[lib.index('if MadeiraConfig.flag("MADEIRA_RUNTIME_SETTINGS") {'):]
_rt = _rt[:_rt.index('\n            }\n')]
check('DisplayRateSettings()' in _rt and 'RuntimeMemorySyncSettings(' in _rt,
      'MADEIRA_RUNTIME_SETTINGS=0 hides both sections')
print('check-runtime-settings:', 'FAIL' if failures else 'PASS')
sys.exit(1 if failures else 0)
