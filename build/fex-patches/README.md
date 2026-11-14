# Madeira's FEX patches

Changes to FEX that Madeira needs and that live in this repository, not in
the FEX submodule's repository. `apply.sh` applies them, in file-name order,
to the FEX working tree before `build/fex-arm64ec/build.sh` and
`build/fex-wow64/build.sh` build `xtajit64.dll` and `xtajit.dll`; it skips a
patch that is already applied, and `apply.sh --revert` takes them out. The
FEX submodule pin does not change.

These patches are for Madeira only and are not to be sent to FEX-Emu.

| Patch | What it fixes |
|---|---|
| `0001-windows-ios-smc-traps-per-16k-host-page.patch` | Self-modifying-code write traps per 16 KB iOS host page, both modules (The Escapists 2, Project Zomboid) |
| `0002-ios-wow64-region-c.patch` | Register C separately from the main JIT pool for WoW64 executable allocations; use the same bounded C RX-to-RW handling for atomics in both FEX PE paths. |
| `0003-steam-hotspot-stages.patch` | Opt-in CEF translation/cache stage timing in both PE paths. `apply.sh` also installs the shared `SteamProbe.h` and `steam_probe_abi.h` headers. No FEX submodule pin change. |
| `0004-ios-l1-cache-index.patch` | Opt-in L1 address mixing in every C++ and emitted ARM64 reader, writer and invalidation path. Uses the existing cache capacity; the immutable per-PE selection is made before InitCore. See `docs/steam-cache-lookup.md`. |
| `0005-steam-compile-reasons.patch` | Independent opt-in compilation observations using decoder byte snapshots, process/manager identity and the actual output buffer serial. Bounded host-owned history, no guest reads and no code-cache policy change. See `docs/steam-compile-reasons.md`. |
| `0006-dfe-scratch-ra-sampling.patch` | Independently switchable per-pass DFE scratch reuse (MADEIRA_FEX_DFE_REUSE, default on; PE initialization in 0005), with bounded vector retention and unchanged CFG/propagation guards; opt-in 1/64 RA invocation timing for setup/check/reverse/forward/cleanup. `apply.sh` installs `DFEScratch.h`. See `docs/steam-dfe-ra.md`. |
| `0007-previous-code-generation.patch` | Experimental default-off CEF previous-generation reuse through dispatcher-only owner migration; one retained buffer up to 128 MiB, existing invalidation and execution references, no new cross-generation persistent links. `apply.sh` installs `PreviousCode.h`; PE initialization is in 0005. See `docs/steam-previous-code.md`. |

A patch must apply on the current FEX pin. When the pin moves, rebase the
patches onto it (or drop a patch the new pin already covers).
