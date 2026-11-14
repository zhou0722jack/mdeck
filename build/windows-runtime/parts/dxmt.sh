#!/usr/bin/env bash
set -euo pipefail
R="${ROOT:?}"
TC="$R/toolchains/llvm-mingw-20260421-ucrt-macos-universal/bin"
bash "$R/build/dxmt-patches/apply.sh"
for arch in arm64ec aarch64; do
    W="$R/wine/build-arm64ec"
    [ "$arch" != aarch64 ] || W="$R/wine/build-macos"
    B="$R/dxmt/build-$arch"
    X="$W/dxmt-$arch.ini"
    sed "s|@GLOBAL_SOURCE_ROOT@|$R|g" "$R/dxmt/build-$arch-win.txt" > "$X"
    if [ ! -f "$B/build.ninja" ]; then
        SDKROOT="$(xcrun --sdk macosx --show-sdk-path)" meson setup "$B" "$R/dxmt" \
            --cross-file "$X" --native-file "$R/dxmt/build-osx.txt" --buildtype release \
            -Dwine_build_path="$W" -Dwine_builtin_dll=true -Denable_nvapi=true
    fi
    SDKROOT="$(xcrun --sdk macosx --show-sdk-path)" meson compile -C "$B" -j "${JOBS:-8}"
    DEST="$R/app/Madeira/$arch-windows"
    for m in d3d11/d3d11.dll dxgi/dxgi.dll d3d10/d3d10core.dll winemetal/winemetal.dll; do
        [ "$arch:$m" != aarch64:d3d10/d3d10core.dll ] || continue
        "$TC/$arch-w64-mingw32-strip" --strip-debug -o "$DEST/$(basename "$m")" "$B/src/$m"
    done
    if [ "$arch" = arm64ec ]; then
        for pair in 'd3d9/d3d9.dll:d3d9.dll' 'nvapi/nvapi64.dll:nvapi64.dll'; do
            "$TC/$arch-w64-mingw32-strip" --strip-debug -o "$DEST/${pair#*:}" "$B/src/${pair%:*}"
        done
    fi
done
# Retain the actual import library used by madeira_d3d12's -lwinemetal.
LIB="$R/dxmt/build-arm64ec/src/winemetal"
if [ ! -s "$LIB/libwinemetal.dll.a" ]; then
    test -s "$LIB/winemetal.dll.a"
    cp "$LIB/winemetal.dll.a" "$LIB/libwinemetal.dll.a"
fi
