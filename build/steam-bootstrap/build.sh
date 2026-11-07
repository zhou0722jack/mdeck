#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compiler="$repo_root/toolchains/llvm-mingw-20260421-ucrt-macos-universal/bin/i686-w64-mingw32-clang"
[[ -x "$compiler" ]] || { echo "Missing pinned llvm-mingw compiler" >&2; exit 1; }
"$compiler" -Os -nostdlib -fno-builtin -fno-stack-protector -Wl,--subsystem,windows,--entry,mainCRTStartup,--no-insert-timestamp \
  -o "$repo_root/app/Madeira/BundledInstallers/SteamBootstrap.exe" \
  "$repo_root/build/steam-bootstrap/bootstrap.c" -lkernel32
python3 "$repo_root/tools/check-steam-bootstrap-pe.py" "$repo_root/app/Madeira/BundledInstallers/SteamBootstrap.exe"
