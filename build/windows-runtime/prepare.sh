#!/usr/bin/env bash
# Windows-only preparation; changes here do not invalidate unrelated graphics.
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
brew install cmake ninja meson pkg-config bison flex
export PATH="$(brew --prefix bison)/bin:$PATH"
bash "$R/tools/build/setup-llvm-mingw.sh"
git -C "$R" submodule update --init --recursive wine dxmt FEX
xcodebuild -downloadComponent MetalToolchain
bash "$R/tools/build/build-shader-headers.sh"
