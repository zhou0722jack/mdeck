#!/usr/bin/env bash
# Native iOS unix-side fixes must not invalidate the Windows PE runtime cache.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
for patch in "$repo_root"/build/ntdll-unix/patches/*.patch; do
    if git -C "$repo_root/wine" apply --reverse --check "$patch" 2>/dev/null; then
        echo "wine-ios-unix-patches: $(basename "$patch") already applied"
    elif git -C "$repo_root/wine" apply --check "$patch" 2>/dev/null; then
        git -C "$repo_root/wine" apply "$patch"
        echo "wine-ios-unix-patches: applied $(basename "$patch")"
    else
        echo "ERROR: $(basename "$patch") does not match the pinned Wine sources" >&2
        exit 1
    fi
done
