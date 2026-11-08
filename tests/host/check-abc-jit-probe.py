#!/usr/bin/env python3
"""Verify borrowing/restoring existing A/B/C bytes; never starts Wine or builds an IPA."""
import platform
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
probe = app / 'AppEntryJITProbe.c'
source = probe.read_text()
for forbidden in ['vm_allocate(', 'vm_deallocate(', 'vm_remap(', 'vm_protect(',
                  'jit26_prepare_region(', 'jit26_detach(', 'sysctl(']:
    assert forbidden not in source, forbidden
assert '#define ENTRY_PROBE_BYTES 8' in source
assert 'probe_sealed = 1;' in source and 'if (!probe_bound || probe_sealed)' in source
assert 'probe_report.available_mask == 7 ? 42 : 1' in source
assert 'probe_original[ENTRY_PROBE_REGIONS][2]' in source
assert 'memcpy((void *)rw, probe_original[region], ENTRY_PROBE_BYTES)' in source
assert 'memcmp((const void *)rx, probe_original[region], ENTRY_PROBE_BYTES)' in source
swift = (app / 'AppEntryJIT.swift').read_text()
assert 'canProbe: { StikJITHelper.poolTaken }' in swift
assert 'StikJITHelper.bindEntryProbe()' in swift and 'jit_entry_probe_copy_report(&report)' in swift
assert 'ForEach(model.regionResults)' in swift
assert 'if result == 42 || result == 1' in swift

with tempfile.TemporaryDirectory(prefix='mdeck-abc-probe-') as directory:
    folder = Path(directory)
    subprocess.run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios18.0',
                    '-fsyntax-only', '-Wall', '-Wextra', '-Werror', str(probe)], check=True)
    if platform.machine() == 'arm64':
        fixture = (root / 'tests/host/fixtures/ABCJITProbeCheck.c').read_text()
        compiled = folder / 'Check.c'
        compiled.write_text(fixture.replace('PROBE_SOURCE', str(probe)))
        for optimization in ['-O0', '-O2']:
            binary = folder / 'check'
            subprocess.run(['xcrun', 'clang', optimization, '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-I', str(app), str(compiled), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
    else:
        print('SKIP: native ARM64 component execution on this host; iOS syntax check completed')
print('PASS: no allocation/reservation/BRK in the probe; real iPad execution and Steam acceptance remain UNRUN.')
