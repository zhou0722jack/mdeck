#!/usr/bin/env python3
"""Validate the generated freestanding i386 bootstrap without running it."""
from pathlib import Path
import struct
import sys

data = Path(sys.argv[1]).read_bytes()
assert data[:2] == b'MZ'
pe = struct.unpack_from('<I', data, 0x3c)[0]
assert data[pe:pe + 4] == b'PE\0\0'
assert struct.unpack_from('<H', data, pe + 4)[0] == 0x14c
assert struct.unpack_from('<H', data, pe + 24)[0] == 0x10b
assert struct.unpack_from('<H', data, pe + 24 + 68)[0] == 2, 'Controller must have no console window'
sections = struct.unpack_from('<H', data, pe + 6)[0]
optional_size = struct.unpack_from('<H', data, pe + 20)[0]
section_table = pe + 24 + optional_size
def offset(rva):
    for i in range(sections):
        at = section_table + i * 40
        virtual_size, va, raw_size, raw = struct.unpack_from('<IIII', data, at + 8)
        if va <= rva < va + max(virtual_size, raw_size):
            delta = rva - va
            assert delta < raw_size
            return raw + delta
    raise AssertionError(f'Unmapped RVA {rva:x}')
import_rva = struct.unpack_from('<I', data, pe + 24 + 104)[0]
at = offset(import_rva)
names = set()
for i in range(32):
    record = struct.unpack_from('<IIIII', data, at + i * 20)
    if record == (0, 0, 0, 0, 0): break
    start = offset(record[3]); end = data.index(b'\0', start)
    names.add(data[start:end].lower())
else: raise AssertionError('Unterminated import table')
assert names == {b'kernel32.dll'}, names
for path in ['C:\\Madeira\\Installers\\SteamSetup.exe', 'C:\\Program Files\\Steam Client\\Steam.exe',
             'C:\\Madeira\\Installers\\SteamLibraries.config.vdf', 'C:\\Madeira\\Installers\\SteamLibraries.steamapps.vdf']:
    assert path.encode('utf-16-le') in data
assert 'C:\\windows\\system32\\explorer.exe'.encode('utf-16-le') in data
assert 'C:\\Madeira\\Installers\\SteamDesktop.command'.encode('utf-16-le') in data
for function in [b'LoadLibraryW', b'GetProcAddress', b'Wow64DisableWow64FsRedirection', b'Wow64RevertWow64FsRedirection']:
    assert function in data, function
assert 'user32.dll'.encode('utf-16-le') in data
assert b'controller GUI station and desktop retained' in data
assert b'native system32 explorer started; redirection restored' in data
print('PASS: generated i386 Steam session controller and fixed installer/client paths')
