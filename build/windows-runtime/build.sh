#!/usr/bin/env bash
# Independently reuse source owners, then validate the assembled Windows farm.
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TC="$R/toolchains/llvm-mingw-20260421-ucrt-macos-universal/bin"
export PATH="$TC:$PATH"
export JOBS="${JOBS:-$(sysctl -n hw.ncpu)}"
export ROOT="$R"
python3 "$R/build/windows-runtime/parts.py" build all
