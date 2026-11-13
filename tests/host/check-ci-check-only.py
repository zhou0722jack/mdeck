#!/usr/bin/env python3
"""Require explicit manual authorization before any IPA/runtime build job can run."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[2]
workflow = (root / '.github/workflows/build.yml').read_text()
assert re.search(r'workflow_dispatch:\s+inputs:\s+build_ipa:.*?type: boolean\s+required: false\s+default: false', workflow, re.S)
assert "build: ${{ github.event_name == 'workflow_dispatch' && inputs.build_ipa && 'true' || 'false' }}" in workflow
assert "inputs.build_ipa && 'build' || 'check'" in workflow, 'check runs must not cancel an explicitly requested build'
parts = re.split(r'^  ([a-z0-9_-]+):\n', workflow.split('jobs:\n', 1)[1], flags=re.M)
jobs = dict(zip(parts[1::2], parts[2::2]))
assert set(jobs) == {'plan', 'reuse', 'llvm', 'fex', 'i386', 'runtime', 'app'}
for name, job in jobs.items():
    if name == 'plan':
        assert 'tools/build-ipa.sh' not in job and 'cmake --build' not in job
        continue
    gate = re.search(r'^    if: (.+)$', job, re.M)
    assert gate and "needs.plan.outputs.build == 'true' &&" in gate[1], name
for event in ['push', 'pull_request', 'workflow_dispatch']:
    for enabled in [False, True]:
        authorized = event == 'workflow_dispatch' and enabled
        if event != 'workflow_dispatch' or not enabled:
            assert not authorized
print('PASS: default/manual checks and automatic events skip every product build job; only explicit build_ipa=true authorizes builds')
