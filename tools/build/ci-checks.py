#!/usr/bin/env python3
"""Run one CI check group and write a receipt only after the entire group passes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[2]
groups = json.loads((root / 'tools/build/ci-check-groups.json').read_text())
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('group', choices=groups)
parser.add_argument('--verify', action='store_true', help='Validate a restored pass receipt without rerunning checks')
args = parser.parse_args()
if os.environ.get('GITHUB_ACTIONS') != 'true':
    parser.error('Run these checks through GitHub Actions.')

receipt = root / '.ci-checks' / f'{args.group}.json'
tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=root, text=True).strip()
if args.verify:
    saved = json.loads(receipt.read_text())
    if (saved.get('group') != args.group or saved.get('tree') != tree or
            [item.get('check') for item in saved.get('checks', [])] != groups[args.group]):
        parser.error('Cached check receipt does not match this source tree and check list.')
    print(f'Reused exact pass receipt: {args.group}, tree={tree}', flush=True)
    sys.exit(0)
receipt.unlink(missing_ok=True)
results = []
for name in groups[args.group]:
    path = root / 'tests/host' / name
    print(f'::group::{name}', flush=True)
    started = time.monotonic()
    try:
        subprocess.run([sys.executable, '-u', str(path)], cwd=root, check=True)
    finally:
        elapsed = time.monotonic() - started
        print(f'{name}: {elapsed:.2f}s\n::endgroup::', flush=True)
    results.append({'check': name, 'seconds': round(elapsed, 3)})

receipt.parent.mkdir(parents=True, exist_ok=True)
receipt.write_text(json.dumps({
    'group': args.group,
    'tree': tree,
    'checks': results,
}, indent=2) + '\n')
summary = os.environ.get('GITHUB_STEP_SUMMARY')
if summary:
    with open(summary, 'a') as stream:
        stream.write(f'### {args.group} checks\n\n| Check | Seconds |\n| --- | ---: |\n')
        for result in results:
            stream.write(f"| {result['check']} | {result['seconds']:.3f} |\n")
