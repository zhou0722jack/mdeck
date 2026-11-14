#!/usr/bin/env python3
"""Independently cache Windows runtime owners, then assemble a checked farm.
The outer `windows` component is retained as the package/import-closure gate.
"""
import argparse
import fnmatch
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PARTS = json.loads((ROOT / 'build/windows-runtime/parts.json').read_text())


def runtime_module():
    spec = importlib.util.spec_from_file_location('runtime_components', ROOT / 'tools/build/runtime-components.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def digest(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def outer_spec():
    return json.loads((ROOT / 'tools/build/runtime-components.json').read_text())['windows']


def prebuilt():
    return set(outer_spec()['prebuilt'])


def owner(path):
    if path.endswith(('/README.md', '/.gitkeep')):
        return None
    if path in prebuilt():
        return None  # versioned fixtures never enter a compiled owner's cache
    if path in ('arm64ec-windows/dockhost.exe', 'arm64ec-windows/dock-notices.txt'):
        return None
    exact = [name for name, spec in PARTS.items() if name != 'wine' and any(
        fnmatch.fnmatchcase(path, pattern) for pattern in spec['outputs'])]
    if len(exact) > 1:
        raise ValueError('ambiguous Windows owner: ' + path)
    if exact:
        return exact[0]
    return 'wine' if any(fnmatch.fnmatchcase(path, pattern) for pattern in PARTS['wine']['outputs']) else None


def inventory():
    prefix = 'app/Madeira/'
    return {p.removeprefix(prefix) for p in git('ls-files', 'app/Madeira').splitlines()
            if p.startswith(prefix) and owner(p.removeprefix(prefix)) is not None} | {
            p for p in outer_spec()['required'] if owner(p) is not None}


def input_key(name, sdk, visiting=()):
    if name in visiting:
        raise ValueError('cyclic Windows dependencies: ' + name)
    spec = PARTS[name]
    tracked = git('ls-files', '--cached', '--others', '--exclude-standard').splitlines()
    patterns = spec['inputs'] + ['build/windows-runtime/parts.py', 'build/windows-runtime/prepare.sh',
                                'tools/build/build-runtime-component.sh']
    inputs = {p: digest((ROOT / p).read_bytes()) for p in tracked if (ROOT / p).is_file()
              and any(fnmatch.fnmatchcase(p, pattern) for pattern in patterns)}
    # Only this owner's output inventory participates. Rebuilt bytes never do.
    outputs = sorted(p for p in inventory() if owner(p) == name)
    pins = {p: git('rev-parse', 'HEAD:' + p) for p in spec['pins']}
    dependencies = {p: input_key(p, sdk, visiting + (name,)) for p in spec['dependencies']}
    return digest(json.dumps([sdk, spec, pins, inputs, outputs, dependencies], sort_keys=True).encode())


def cache_dir(name):
    return ROOT / '.runtime-cache/windows-parts' / name


def dependencies(name):
    result = []
    for dep in PARTS[name]['dependencies']:
        for ancestor in dependencies(dep) + [dep]:
            if ancestor not in result:
                result.append(ancestor)
    return result


def check_support(path, metadata):
    if not isinstance(metadata, dict) or set(metadata) != {'sha256', 'executable'}:
        raise ValueError('invalid support metadata: ' + path)
    if not isinstance(metadata['executable'], bool):
        raise ValueError('invalid support mode: ' + path)


def validate(name, manifest, read, read_support, sdk):
    runtime = runtime_module()
    if manifest.get('schema') != 1 or manifest.get('key') != input_key(name, sdk):
        raise ValueError(name + ': Windows source/SDK mismatch')
    deps = {dep: input_key(dep, sdk) for dep in PARTS[name]['dependencies']}
    if manifest.get('dependencies') != deps:
        raise ValueError(name + ': Windows dependency keys mismatch')
    files, support = manifest.get('files', {}), manifest.get('support', {})
    expected = {p for p in inventory() if owner(p) == name}
    # Fixed outputs may first appear on a clean bootstrap before inventory grows.
    expected |= {p for p in PARTS[name]['outputs'] if not any(c in p for c in '*?[')}
    if not isinstance(files, dict) or not expected <= files.keys():
        raise ValueError(name + ': missing Windows outputs')
    if not isinstance(support, dict) or set(support) != set(PARTS[name]['support']):
        raise ValueError(name + ': missing or unexpected build support')
    for path, sha in files.items():
        runtime.safe_path(path)
        if owner(path) != name:
            raise ValueError(name + ': output belongs to another owner: ' + path)
        data = read(path)
        runtime.check_binary(path, data)
        if digest(data) != sha:
            raise ValueError(name + ': output checksum mismatch: ' + path)
    for path, metadata in support.items():
        runtime.safe_path(path)
        check_support(path, metadata)
        data = read_support(path)
        if not data or digest(data) != metadata['sha256']:
            raise ValueError(name + ': build support checksum mismatch: ' + path)


def stage(name, sdk):
    runtime = runtime_module()
    cache = cache_dir(name)
    manifest = json.loads((cache / 'manifest.json').read_text())
    validate(name, manifest, lambda p: runtime.read_regular(cache / 'files', p),
             lambda p: runtime.read_regular(cache / 'support', p), sdk)
    # Every byte validated before any destination is replaced.
    for path in manifest['files']:
        destination = ROOT / 'app/Madeira' / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() or ROOT.resolve() not in destination.parent.resolve().parents:
            raise ValueError('refusing Windows output symlink: ' + path)
        shutil.copyfile(cache / 'files' / path, destination)
    for path, metadata in manifest['support'].items():
        destination = ROOT / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() or ROOT.resolve() not in destination.parent.resolve().parents:
            raise ValueError('unsafe build support destination: ' + path)
        shutil.copyfile(cache / 'support' / path, destination)
        destination.chmod(0o755 if metadata['executable'] else 0o644)
    return manifest


def snapshot(name, sdk):
    runtime = runtime_module()
    bundle = ROOT / 'app/Madeira'
    files = {p.relative_to(bundle).as_posix(): digest(p.read_bytes()) for p in bundle.rglob('*')
             if p.is_file() and owner(p.relative_to(bundle).as_posix()) == name}
    support = {p: {'sha256': digest(runtime.read_regular(ROOT, p)),
                   'executable': bool((ROOT / p).stat().st_mode & 0o111)} for p in PARTS[name]['support']}
    manifest = {'schema': 1, 'key': input_key(name, sdk), 'files': files, 'support': support,
                'dependencies': {p: input_key(p, sdk) for p in PARTS[name]['dependencies']}}
    validate(name, manifest, lambda p: runtime.read_regular(bundle, p), lambda p: runtime.read_regular(ROOT, p), sdk)
    cache = cache_dir(name)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache.parent) as tmp:
        tmp = Path(tmp)
        for category, names in [('files', files), ('support', support)]:
            for path in names:
                destination = tmp / category / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile((bundle if category == 'files' else ROOT) / path, destination)
        (tmp / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        if cache.exists():
            shutil.rmtree(cache)
        shutil.copytree(tmp, cache)
    return manifest


def build_part(name, sdk):
    if os.environ.get('MADEIRA_RUNTIME_REUSE') == '1':
        try:
            stage(name, sdk)
            print(f'windows/{name}: exact source/SDK cache reused', flush=True)
            return
        except (OSError, ValueError, KeyError) as error:
            print(f'windows/{name}: rebuild required: {error}', flush=True)
    # Only a cache miss needs dependencies' link support on this runner.
    for dep in dependencies(name):
        stage(dep, sdk)
    if name in ('dxmt', 'd3d12'):
        subprocess.run(['bash', str(ROOT / 'build/dxmt-patches/apply.sh')], cwd=ROOT, check=True)
    subprocess.run(['bash', str(ROOT / PARTS[name]['recipe'])], cwd=ROOT,
                   env=dict(os.environ, ROOT=str(ROOT), JOBS=os.environ.get('JOBS', str(os.cpu_count() or 8)),
                            PATH=str(ROOT / 'toolchains/llvm-mingw-20260421-ucrt-macos-universal/bin')
                            + os.pathsep + os.environ['PATH']), check=True)
    snapshot(name, sdk)


def build_all(sdk):
    for name in PARTS:
        build_part(name, sdk)
    # Prebuilt programs are source files, never inherited from a runtime cache.
    runtime = runtime_module()
    for path in prebuilt():
        runtime.check_binary(path, runtime.read_regular(ROOT / 'app/Madeira', path))
    # Validation only: never silently build extra Wine modules after snapshot.
    manifests = {name: stage(name, sdk) for name in PARTS}
    for arch in ['arm64ec', 'aarch64']:
        farm = ROOT / f'app/Madeira/{arch}-windows'
        files = {p.name.lower(): p.read_bytes() for p in farm.iterdir() if p.is_file()}
        missing = runtime.missing_imports(files)
        if missing:
            raise ValueError(f'{arch}: split Windows assembly has missing imports: {sorted(missing)}; update the Wine inventory')
    receipt = {'schema': 1, 'sdk': sdk, 'parts': {name: {'key': m['key'], 'files': m['files'],
               'dependencies': m['dependencies']} for name, m in manifests.items()}}
    (ROOT / 'app/Madeira/windows-runtime-parts.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print('Windows parts assembled with checked source keys, checksums and import closure', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['keys', 'build', 'stage'])
    parser.add_argument('name', nargs='?', default='all')
    args = parser.parse_args()
    sdk = runtime_module().sdk_key()
    if args.name != 'all' and args.name not in PARTS:
        parser.error('unknown Windows part')
    names = list(PARTS) if args.name == 'all' else [args.name]
    if args.action == 'keys':
        for name in names:
            print(f'{name}=windows-part-v1-{name}-{input_key(name, sdk)}')
    elif args.action == 'build' and args.name == 'all':
        build_all(sdk)
    else:
        for name in names:
            (build_part if args.action == 'build' else stage)(name, sdk)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit('ERROR: ' + str(error))
