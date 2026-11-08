#!/usr/bin/env python3
"""Exercise production Win64 staging/migration; never executes Steam or Wine."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import struct
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app/Madeira'
parser = argparse.ArgumentParser()
parser.add_argument('--official-archive', type=Path)
parser.add_argument('--download-official', action='store_true', help='Also verify the production URLSession download against Valve CDN.')
args = parser.parse_args()
source = (APP / 'SteamClient64Bootstrap.swift').read_text()
client = (APP / 'SteamClient.swift').read_text()
content = (APP / 'ContentView.swift').read_text()
assert 'SteamClient64Bootstrap.swift in Sources' in (ROOT / 'app/Madeira.xcodeproj/project.pbxproj').read_text()
assert 'prepareClient: { try await SteamClient.prepare64BitBootstrap() }' in content
assert client.count('wine_process_is_running() == 0, wineserver_is_running() == 0') >= 3
assert client.index('try await SteamClient64Bootstrap.stage') < client.index('try SteamClient64Bootstrap.activate')
assert 'client.bits = 64' in client
assert 'response.url?.host == "client-update.akamai.steamstatic.com"' in source

def pe(machine, magic):
    result = bytearray(512)
    result[:2] = b'MZ'
    struct.pack_into('<I', result, 0x3c, 128)
    result[128:132] = b'PE\0\0'
    struct.pack_into('<H', result, 132, machine)
    struct.pack_into('<H', result, 152, magic)
    return bytes(result)

def archive(data, name='steam.exe'):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, data)
    return result.getvalue()

with tempfile.TemporaryDirectory(prefix='mdeck-client64-') as temporary:
    folder = Path(temporary)
    image = pe(0x8664, 0x20b)
    old = pe(0x14c, 0x10b)
    bundle = archive(image)
    data = {'archiveBytes': len(bundle), 'archiveSHA256': hashlib.sha256(bundle).hexdigest(),
            'imageBytes': len(image), 'imageSHA256': hashlib.sha256(image).hexdigest()}
    (folder / 'release.json').write_text(json.dumps(data))
    for name, value in [('good.zip', bundle), ('old.exe', old), ('bad-arch.zip', archive(old)), ('wrong-name.zip', archive(image, '../steam.exe'))]:
        (folder / name).write_bytes(value)
    main = folder / 'Check.swift'
    fixture = (ROOT / 'tests/host/fixtures/SteamClient64Check.swift').read_text()
    main.write_text(fixture)
    binary = folder / 'check'
    subprocess.run(['xcrun', 'swiftc', '-parse-as-library', str(APP / 'SteamClient64Bootstrap.swift'),
                    str(APP / 'SteamRuntime.swift'), str(APP / 'Localization.swift'), str(APP / 'SteamKeyValues.swift'),
                    str(main), '-o', str(binary)], check=True)
    command = [str(binary), str(folder)]
    if args.official_archive:
        command.append(str(args.official_archive.resolve()))
    if args.download_official:
        command.append('--download-official')
    subprocess.run(command, check=True)

    # Compile the actual updated controller into a disposable PE only.
    compiler = ROOT / 'toolchains/llvm-mingw-20260421-ucrt-macos-universal/bin/i686-w64-mingw32-clang'
    if compiler.exists():
        controller = folder / 'SteamBootstrap.exe'
        subprocess.run([str(compiler), '-Os', '-nostdlib', '-fno-builtin', '-fno-stack-protector',
                        '-Wl,--subsystem,windows,--entry,mainCRTStartup,--no-insert-timestamp', '-o', str(controller),
                        str(ROOT / 'build/steam-bootstrap/bootstrap.c'), '-lkernel32'], check=True)
        subprocess.run(['python3', str(ROOT / 'tools/check-steam-bootstrap-pe.py'), str(controller)], check=True)
        pe_bytes = controller.read_bytes()
        assert b'GetBinaryTypeW' in pe_bytes
        assert 'C:\\Madeira\\Installers\\Steam64.exe'.encode('utf-16le') in pe_bytes
        assert b'verified x86_64 bootstrap activated after setup' in pe_bytes
        print('PASS: real freestanding setup controller links the Win64 architecture check and activation path')
    else:
        print('SKIP: controller PE check requires pinned cross compiler')
print('No Steam/Wine execution, IPA build, account access or physical-device test.')
