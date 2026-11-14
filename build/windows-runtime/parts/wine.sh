#!/usr/bin/env bash
set -euo pipefail
R="${ROOT:?}"
if command -v brew >/dev/null 2>&1; then
    export PATH="$(brew --prefix bison)/bin:$PATH"
fi
bash "$R/tools/build/build-wine.sh"
modules=()
while IFS= read -r name; do
    [ "$name" = ntdll ] || modules+=("$name")
done < <(python3 "$R/build/windows-runtime/targets.py" arm64ec list)
[ ${#modules[@]} -gt 0 ] || { echo 'No ARM64EC Wine modules selected' >&2; exit 1; }
bash "$R/build/wine-pe/build-modules.sh" "${modules[@]}"
bash "$R/build/wine-pe/build-ntdll.sh"
python3 "$R/build/windows-runtime/targets.py" aarch64 install
DEST="$R/app/Madeira/vulkan/arm64ec-windows" bash "$R/build/wine-pe/build-modules.sh" winevulkan vulkan-1
# DXMT consumers need these exact link inputs and the host winebuild executable,
# even on a fresh runner that restores the Wine binary cache.
for pair in build-arm64ec:arm64ec build-macos:aarch64; do
    tree="${pair%:*}"; arch="${pair#*:}"
    make -C "$R/wine/$tree" -j"${JOBS:-8}" tools/winebuild/winebuild \
        "libs/winecrt0/$arch-windows/libwinecrt0.a" \
        "dlls/ntdll/$arch-windows/libntdll.a" "dlls/dbghelp/$arch-windows/libdbghelp.a"
done
