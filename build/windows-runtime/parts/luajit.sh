#!/usr/bin/env bash
set -euo pipefail
R="${ROOT:?}"
LUA="$R/toolchains/luajit-a4c064539ea931274d407e1249b4bb575424a0f4"
if [ ! -d "$LUA/.git" ]; then
    git init -q "$LUA"
    git -C "$LUA" fetch --depth 1 https://github.com/LuaJIT/LuaJIT.git a4c064539ea931274d407e1249b4bb575424a0f4
    git -C "$LUA" checkout -q FETCH_HEAD
fi
[ "$(git -C "$LUA" rev-parse HEAD)" = a4c064539ea931274d407e1249b4bb575424a0f4 ] || exit 1
LUAJIT_SRC="$LUA" bash "$R/build/luajit-x64/build.sh"
