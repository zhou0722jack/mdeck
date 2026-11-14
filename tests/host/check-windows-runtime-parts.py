#!/usr/bin/env python3
"""Actions-only tests of real Windows sub-cache keys, restore and assembly.
Product commands are controlled fixtures; no runtime/IPA builds here.
"""
import copy
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Use GitHub Actions'
ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parts = load('windows_parts', ROOT / 'build/windows-runtime/parts.py')
helpers = load('runtime_fixtures', ROOT / 'tests/host/check-runtime-components.py')
real_contract = json.loads((ROOT / 'tools/build/runtime-components.json').read_text())


class PartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='mdeck-windows-parts-')
        self.root = Path(self.tmp.name)
        self.previous = parts.ROOT
        parts.ROOT = self.root
        self.write('tools/build/runtime-components.json', json.dumps(real_contract).encode())
        self.write('.gitignore', b'wine/\ndxmt/\n.runtime-cache/\n')
        for file in ['tools/build/runtime-components.py', 'tools/check-wine-media-dlls.py',
                     'build/windows-runtime/parts.py', 'build/windows-runtime/targets.py']:
            self.write(file, (ROOT / file).read_bytes())
        for name, spec in parts.PARTS.items():
            self.write(spec['recipe'], b'#!/bin/sh\nexit 0\n')
            for path in spec['support']:
                f = self.write(path, b'build support\n')
                f.chmod(0o755 if path.endswith('/winebuild') else 0o644)
        for path in real_contract['windows']['required'] + real_contract['windows']['prebuilt']:
            self.write('app/Madeira/' + path, helpers.fixture(path))
        for spec in parts.PARTS.values():
            for path in spec['outputs']:
                if not any(c in path for c in '*?['):
                    self.write('app/Madeira/' + path, helpers.fixture(path))
        self.write('app/Madeira/compat/love/lua51.dll.version', b'fixed-version\n')
        # Representative paths covering every independent input owner.
        for path in ['build/fex-patches/probe.h', 'build/fex-wow64/build.sh', 'build/fex-arm64ec/build.sh',
                     'build/dxmt-patches/example.patch', 'build/windows-runtime/patches/example.patch',
                     'build/faultrep/faultrep.c', 'build/luajit-x64/build.sh', 'madeira-d3d12/src/pe/test.c',
                     'tools/build/setup-llvm-mingw.sh', 'app/Madeira/Library.swift']:
            self.write(path, b'baseline\n')
        self.git('init', '-q')
        self.git('config', 'user.name', 'Parts fixture')
        self.git('config', 'user.email', 'parts@example.invalid')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.pin = self.git('rev-parse', 'HEAD')
        for pin in ['wine', 'FEX', 'dxmt']:
            self.git('update-index', '--add', '--cacheinfo', f'160000,{self.pin},{pin}')
        self.git('commit', '-qm', 'pins')
        self.sdk = 'sdk-fixture'

    def tearDown(self):
        parts.ROOT = self.previous
        self.tmp.cleanup()

    def write(self, path, data):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        return file

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def keys(self, sdk=None):
        return {name: parts.input_key(name, sdk or self.sdk) for name in parts.PARTS}

    def snapshots(self):
        return {name: parts.snapshot(name, self.sdk) for name in parts.PARTS}

    @contextmanager
    def controlled_builds(self, fail=False):
        # Git check_output also calls subprocess.run internally. Preserve real
        # source-key reads while controlling only the product recipe commands.
        real_run = subprocess.run
        commands = []
        def run(command, *args, **kwargs):
            if isinstance(command, list) and command[0] == 'bash':
                commands.append(command)
                if fail:
                    raise subprocess.CalledProcessError(86, command)
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, *args, **kwargs)
        with patch.object(parts.subprocess, 'run', side_effect=run):
            yield commands

    def test_invalidation_graph(self):
        cases = {
            'build/fex-patches/probe.h': {'fex32', 'fex64'},
            'build/fex-wow64/build.sh': {'fex32'},
            'build/fex-arm64ec/build.sh': {'fex64'},
            'build/dxmt-patches/example.patch': {'dxmt', 'd3d12'},
            'build/windows-runtime/patches/example.patch': {'wine', 'dxmt', 'd3d12'},
            'build/faultrep/faultrep.c': {'helpers'},
            'build/luajit-x64/build.sh': {'luajit'},
            'madeira-d3d12/src/pe/test.c': {'d3d12'},
            'app/Madeira/Library.swift': set(),
            'tools/build/setup-llvm-mingw.sh': set(parts.PARTS),
        }
        before = self.keys()
        for path, expected in cases.items():
            original = (self.root / path).read_bytes()
            self.write(path, original + b'changed\n')
            changed = {p for p, key in self.keys().items() if key != before[p]}
            self.assertEqual(changed, expected, path)
            self.write(path, original)
        self.assertTrue(all(k != before[p] for p, k in self.keys('other-sdk').items()))
        for pin, expected in [('FEX', {'fex32','fex64'}), ('wine', {'wine','dxmt','d3d12'}), ('dxmt', {'dxmt','d3d12'})]:
            self.git('commit', '--allow-empty', '-qm', 'changed pin')
            other = self.git('rev-parse', 'HEAD')
            self.git('update-index', '--cacheinfo', f'160000,{other},{pin}')
            self.git('commit', '-qm', 'move pin')
            self.assertEqual({p for p,k in self.keys().items() if k != before[p]}, expected)
            self.git('update-index', '--cacheinfo', f'160000,{self.pin},{pin}')
            self.git('commit', '-qm', 'restore pin')
        print('PASS Windows cache graph: FEX-only, each architecture, Wine/DXMT dependencies, app-only and SDK changes')

    def test_cache_hit_does_not_compile(self):
        self.snapshots()
        with patch.dict(os.environ, MADEIRA_RUNTIME_REUSE='1'):
            with self.controlled_builds() as commands:
                for name in parts.PARTS:
                    parts.build_part(name, self.sdk)
                self.assertEqual(commands, [])

    def test_fex_only_rebuild_reuses_wine_and_dxmt(self):
        self.snapshots()
        self.write('build/fex-patches/probe.h', b'changed\n')
        with patch.dict(os.environ, MADEIRA_RUNTIME_REUSE='1'):
            with self.controlled_builds() as commands:
                for name in parts.PARTS:
                    parts.build_part(name, self.sdk)
        self.assertEqual([Path(c[1]).name for c in commands], ['fex32.sh','fex64.sh'])

    def test_fresh_runner_support_restores_and_rejects_bad_support(self):
        self.snapshots()
        for name in ['wine', 'dxmt']:
            for path in parts.PARTS[name]['support']:
                (self.root / path).unlink()
            parts.stage(name, self.sdk)
            for path in parts.PARTS[name]['support']:
                self.assertEqual((self.root / path).read_bytes(), b'build support\n')
                self.assertEqual(bool((self.root / path).stat().st_mode & 0o111), path.endswith('/winebuild'))
        wine_lib = parts.PARTS['wine']['support'][1]
        (parts.cache_dir('wine') / 'support' / wine_lib).write_bytes(b'corrupt')
        output = self.root / 'app/Madeira/arm64ec-windows/ntdll.dll'
        before = output.read_bytes()
        with self.assertRaisesRegex(ValueError, 'support checksum'):
            parts.stage('wine', self.sdk)
        self.assertEqual(output.read_bytes(), before)

    def test_wrong_owner_architecture_checksum_and_dependency_rejected(self):
        snapshots = self.snapshots()
        cache = parts.cache_dir('fex32')
        manifest = snapshots['fex32']
        path = 'aarch64-windows/xtajit.dll'
        broken = helpers.pe(0x8664)
        (cache / 'files' / path).write_bytes(broken)
        manifest['files'][path] = parts.digest(broken)
        (cache / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'architecture'):
            parts.stage('fex32', self.sdk)
        manifest = snapshots['dxmt']
        manifest['dependencies']['wine'] = 'wrong'
        (parts.cache_dir('dxmt') / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'dependency keys'):
            parts.stage('dxmt', self.sdk)
        manifest = snapshots['fex64']
        manifest['files']['aarch64-windows/xtajit.dll'] = parts.digest(broken)
        (parts.cache_dir('fex64') / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'another owner'):
            parts.stage('fex64', self.sdk)

    def test_failed_rebuild_preserves_previous_caches(self):
        self.snapshots()
        before = {n: (parts.cache_dir(n) / 'manifest.json').read_bytes() for n in parts.PARTS}
        self.write('build/fex-patches/probe.h', b'new revision')
        with patch.dict(os.environ, MADEIRA_RUNTIME_REUSE='1'), self.controlled_builds(fail=True):
            with self.assertRaises(subprocess.CalledProcessError):
                parts.build_part('fex32', self.sdk)
        self.assertEqual(before, {n: (parts.cache_dir(n) / 'manifest.json').read_bytes() for n in parts.PARTS})

    def test_source_inventory_not_rebuilt_binary_bytes(self):
        before = self.keys()
        self.write('app/Madeira/aarch64-windows/xtajit.dll', helpers.pe(0xaa64) + b'new build')
        self.assertEqual(before, self.keys())
        self.write('app/Madeira/arm64ec-windows/newwine.dll', helpers.pe(0x8664))
        self.git('add', 'app/Madeira/arm64ec-windows/newwine.dll')
        self.assertEqual({n for n,k in self.keys().items() if k != before[n]}, {'wine','dxmt','d3d12'})

    def test_full_assembly_closure_and_receipt(self):
        self.snapshots()
        with patch.dict(os.environ, MADEIRA_RUNTIME_REUSE='1'), self.controlled_builds() as commands:
            parts.build_all(self.sdk)
            self.assertEqual(commands, [])
        receipt = json.loads((self.root / 'app/Madeira/windows-runtime-parts.json').read_text())
        self.assertEqual(set(receipt['parts']), set(parts.PARTS))
        caller = self.write('app/Madeira/arm64ec-windows/caller.dll', helpers.pe(0x8664, ['absent.dll']))
        self.git('add', 'app/Madeira/arm64ec-windows/caller.dll')
        # The producer snapshot validates its files, final assembly checks imports.
        parts.snapshot('wine', self.sdk)
        parts.snapshot('dxmt', self.sdk)
        parts.snapshot('d3d12', self.sdk)
        with patch.dict(os.environ, MADEIRA_RUNTIME_REUSE='1'):
            with self.assertRaisesRegex(ValueError, 'missing imports'):
                parts.build_all(self.sdk)
        self.assertTrue(caller.is_file())


workflow=(ROOT/'.github/workflows/build.yml').read_text()
for name in parts.PARTS:
    assert f'key: ${{{{ steps.windows-parts.outputs.{name} }}}}' in workflow
    assert f'path: .runtime-cache/windows-parts/{name}' in workflow
    assert f'parts.py build {name}' in workflow
assert 'restore-keys:' not in workflow
assert 'actions/cache/save@v4' in workflow
assert 'runtime-components.py build windows' in workflow
print('PASS workflow: each owner restores/saves exact keys and saves completed owners before a later failure')
if __name__=='__main__':
    unittest.main()
