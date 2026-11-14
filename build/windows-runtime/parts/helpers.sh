#!/usr/bin/env bash
set -euo pipefail
R="${ROOT:?}"
TC="$R/toolchains/llvm-mingw-20260421-ucrt-macos-universal/bin"
bash "$R/build/faultrep/build.sh"
"$TC/arm64ec-w64-mingw32-clang" -shared -O2 -Wl,--no-insert-timestamp \
    -o "$R/app/Madeira/arm64ec-windows/wineios.drv" "$R/build/wineios-drv/wineios.c"
"$TC/x86_64-w64-mingw32-clang" -shared -O2 -nostdlib -fno-stack-protector \
    -Wl,--entry,DllMainCRTStartup,--no-insert-timestamp \
    -o "$R/app/Madeira/arm64ec-windows/tftrace-x64.dll" "$R/build/tftrace/tftrace-x64.c" -lkernel32
