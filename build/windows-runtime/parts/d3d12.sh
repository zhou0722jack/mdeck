#!/usr/bin/env bash
set -euo pipefail
R="${ROOT:?}"
MADEIRA_REQUIRE_KERNELS=1 bash "$R/build/madeira-d3d12/build-pe.sh"
for dll in madeira_d3d12 d3d12 d3d12core; do
    cp "$R/build/madeira-d3d12/out-pe/$dll.dll" "$R/app/Madeira/arm64ec-windows/$dll.dll"
done
