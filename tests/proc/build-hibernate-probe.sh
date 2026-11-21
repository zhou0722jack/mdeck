#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compiler="$root/toolchains/llvm-mingw-20260421-ucrt-macos-universal/bin/i686-w64-mingw32-clang"
resources="$root/app/Madeira/BundledInstallers"
for program in hibernate-probe hibernate-worker; do
  "$compiler" -Os -Wall -Wextra -Werror -municode -mwindows -s -Wl,--no-insert-timestamp \
    "$root/tests/proc/$program.c" -o "$resources/$program.exe"
done
