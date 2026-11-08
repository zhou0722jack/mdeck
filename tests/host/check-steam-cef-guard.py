#!/usr/bin/env python3
"""Synthetic failure handling only; no real Steam or account data."""
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
NATIVE=ROOT/'build/ntdll-unix'
APP=ROOT/'app/Madeira'
virtual=(NATIVE/'virtual_ios.c').read_text()
process=(NATIVE/'process_ios.c').read_text()
assert virtual.count('ios_steam_cef_allocation_result(getenv(')==2
assert process.index('ios_steam_cef_spawn_blocked(getenv(')<process.index('if (!(startup_info = create_startup_info(')
assert 'if (handle == NtCurrentProcess() || !handle)' in process
assert 'compile_one "$BUILD_DIR/steam_cef_guard.c" "steam_cef_guard"' in (NATIVE/'build.sh').read_text()
assert 'SteamClientRuntimeFailure.beginRun()' in (APP/'SteamClient.swift').read_text()
with tempfile.TemporaryDirectory(prefix='mdeck-steam-cef-guard-') as temporary:
    folder=Path(temporary)
    binary=folder/'guard'
    subprocess.run(['xcrun','clang','-std=gnu11','-Wall','-Wextra','-Werror','-pthread',
        '-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(NATIVE),
        str(NATIVE/'steam_cef_guard.c'),str(ROOT/'tests/host/fixtures/SteamCEFGuardCheck.c'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    subprocess.run(['xcrun','clang','-arch','arm64','-isysroot',sdk,'-miphoneos-version-min=18.0',
        '-std=gnu11','-Wall','-Wextra','-Werror','-fsyntax-only',str(NATIVE/'steam_cef_guard.c')],check=True)
    production=(APP/'SteamClientRuntimeFailure.swift').read_text().replace('#if canImport(UIKit)','').replace('#endif','')
    swift=folder/'Check.swift'
    swift.write_text((ROOT/'tests/host/fixtures/SteamCEFFailureCheck.swift').read_text().replace('// PRODUCTION_RUNTIME_FAILURE',production))
    binary=folder/'swift'
    subprocess.run(['xcrun','swiftc','-parse-as-library',str(swift),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
print('PASS: both real allocation entrypoints, process exit/spawn and iOS guard compile wiring')
print('No 32 GB allocation recovery, CEF rendering, IPA build or physical-device acceptance is claimed.')
