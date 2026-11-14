#!/usr/bin/env bash
# Explicit imported Wine DLLs previously added by the monolithic closure pass.
set -euo pipefail
R="${ROOT:?}"
export PATH="$(brew --prefix bison)/bin:$PATH"
bash "$R/tools/build/build-wine.sh"
python3 - "$R" <<'PY'
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('wine_targets', root / 'build/windows-runtime/targets.py')
targets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(targets)
paths = json.loads((root / 'build/windows-runtime/parts.json').read_text())['wine_imports']['outputs']
for arch in ['arm64ec', 'aarch64']:
    names = {Path(p).name for p in paths if p.startswith(arch + '-windows/')}
    selected = targets.targets(arch, names)
    if len(selected) != len(names):
        raise SystemExit('Missing source owner for Wine dependency DLL')
    if arch == 'arm64ec':
        subprocess.run(['bash', str(root / 'build/wine-pe/build-modules.sh'),
                        *(directory for _, _, directory in selected)], check=True)
    else:
        targets.install(arch, selected)
PY
