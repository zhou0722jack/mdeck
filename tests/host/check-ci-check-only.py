#!/usr/bin/env python3
"""Require explicit manual authorization before any IPA/runtime build job can run."""
from pathlib import Path
import json
import os
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
workflow = (root / '.github/workflows/build.yml').read_text()
assert re.search(r'workflow_dispatch:\s+inputs:\s+build_ipa:.*?type: boolean\s+required: false\s+default: false', workflow, re.S)
assert "build: ${{ github.event_name == 'workflow_dispatch' && inputs.build_ipa && 'true' || 'false' }}" in workflow
assert "inputs.build_ipa && 'build' || 'check'" in workflow, 'check runs must not cancel an explicitly requested build'
parts = re.split(r'^  ([a-z0-9_-]+):\n', workflow.split('jobs:\n', 1)[1], flags=re.M)
jobs = dict(zip(parts[1::2], parts[2::2]))
assert set(jobs) == {'plan', 'checks', 'reuse', 'llvm', 'fex', 'i386', 'runtime', 'app'}
for name, job in jobs.items():
    if name in {'plan', 'checks'}:
        assert 'tools/build-ipa.sh' not in job and 'cmake --build' not in job
        continue
    gate = re.search(r'^    if: (.+)$', job, re.M)
    assert gate and "needs.plan.outputs.build == 'true' &&" in gate[1], name
for event in ['push', 'pull_request', 'workflow_dispatch']:
    for enabled in [False, True]:
        authorized = event == 'workflow_dispatch' and enabled
        if event != 'workflow_dispatch' or not enabled:
            assert not authorized

# Checks no longer serialize every native build, but neither IPA delivery path
# can bypass a failed check group. Default success() propagation remains intact.
assert 'tests/host/' not in jobs['plan'] and 'submodule update' not in jobs['plan']
assert 'needs: plan' in jobs['checks']
assert 'group: [frontend, runtime, build]' in jobs['checks']
assert 'fail-fast: false' in jobs['checks']
for name in ['app', 'reuse']:
    needs = re.search(r'^    needs: \[([^\]]+)\]', jobs[name], re.M)
    assert needs and 'checks' in [item.strip() for item in needs[1].split(',')], name
    assert 'always()' not in re.search(r'^    if: (.+)$', jobs[name], re.M)[1]
for name in ['llvm', 'fex', 'i386', 'runtime']:
    assert 'checks' not in re.search(r'^    needs: (.+)$', jobs[name], re.M)[1]
checks = jobs['checks']
assert 'HEAD^{tree}' in checks and 'steps.sdk.outputs.ipa' in checks
assert 'sw_vers; xcrun swiftc --version; python3 --version' in checks
assert 'restore-keys:' not in checks and 'if: ${{ !inputs.rerun_checks }}' in checks
assert "run: python3 tools/build/ci-checks.py '${{ matrix.group }}' --verify" in checks
assert checks.index('name: Run check group') < checks.index('name: Retain successful check receipt')
groups = json.loads((root / 'tools/build/ci-check-groups.json').read_text())
assert set(groups) == {'frontend', 'runtime', 'build'}
names = [name for group in groups.values() for name in group]
assert len(names) == len(set(names)) == 53
for name in names:
    assert (root / 'tests/host' / name).is_file(), name

# The runner must never create/reuse a pass receipt after any check fails.
with tempfile.TemporaryDirectory(prefix='mdeck-check-groups-') as tmp:
    repo = Path(tmp)
    (repo / 'tools/build').mkdir(parents=True)
    (repo / 'tests/host').mkdir(parents=True)
    runner = repo / 'tools/build/ci-checks.py'
    runner.write_text((root / 'tools/build/ci-checks.py').read_text())
    manifest = repo / 'tools/build/ci-check-groups.json'
    manifest.write_text(json.dumps({'fixture': ['first.py', 'second.py']}))
    (repo / 'tests/host/first.py').write_text('print("first passed")\n')
    second = repo / 'tests/host/second.py'
    second.write_text('print("second passed")\n')
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=CI fixture',
                    '-c', 'user.email=ci@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    env = dict(os.environ, GITHUB_ACTIONS='true', GITHUB_STEP_SUMMARY=str(repo / 'summary'))
    command = [sys.executable, str(runner), 'fixture']
    def run(extra=()):
        return subprocess.run(command + list(extra), cwd=repo, env=env, capture_output=True, text=True)
    receipt = repo / '.ci-checks/fixture.json'
    assert run().returncode == 0 and receipt.exists()
    assert run(['--verify']).returncode == 0
    saved = json.loads(receipt.read_text());saved['tree'] = 'wrong'
    receipt.write_text(json.dumps(saved))
    assert run(['--verify']).returncode != 0
    assert run().returncode == 0
    saved = json.loads(receipt.read_text());saved['checks'].pop()
    receipt.write_text(json.dumps(saved))
    assert run(['--verify']).returncode != 0
    second.write_text('raise SystemExit(42)\n')
    assert run().returncode != 0 and not receipt.exists()
    assert run(['--verify']).returncode != 0
print('PASS: explicit build authorization, parallel check gates, exact pass receipts and fail-closed check runner')
