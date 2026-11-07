#!/usr/bin/env bash
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
shopt -s nullglob
for patch in "$R"/build/windows-runtime/patches/*.patch; do
    if git -C "$R/wine" apply --reverse --check "$patch" 2>/dev/null; then
        echo "wine-runtime-patches: $(basename "$patch") already applied"
    elif git -C "$R/wine" apply --check "$patch" 2>/dev/null; then
        git -C "$R/wine" apply "$patch"
        echo "wine-runtime-patches: applied $(basename "$patch")"
    else
        echo "ERROR: $(basename "$patch") does not match the pinned Wine sources" >&2
        exit 1
    fi
done
