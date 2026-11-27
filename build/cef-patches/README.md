# Windows x64 CEF PartitionAlloc 4 GiB experiment

This experiment reduces each Windows x64 PartitionAlloc pool from 16 GiB
to 4 GiB. It includes a Chromium source patch and a fixed-version Valve
paired libcef/chrome_elf binary experiment.

## Source pins

| Source | Revision |
| --- | --- |
| Chromium | `126.0.6478.183`, commit `2e81dea53f5ecdc1c057e4c70ecd66151987296a` |
| Public CEF comparison tree | branch `6478`, commit `a5d51ba9db7ee74a523dc247bd09ec91ba4d7446` |
| Public CEF depot_tools pin | `fca881606e` |

The public CEF tree's `CHROMIUM_BUILD_COMPATIBILITY.txt` specifies that
Chromium tag. Its CEF revision differs from Valve's custom revisions below.

The downloaded Chromium PartitionAlloc subtree archive has SHA-256
`44ed212c9e587be82cf9ff5ad7eb6a7bf96f81d43cc69fb2558385e9bf3c0f48`.
The two additional headers used for cross compilation are the same Chromium
revision's `build/build_config.h` and `build/buildflag.h`.

Sources are available from
[Chromium Gitiles](https://chromium.googlesource.com/chromium/src/+/2e81dea53f5ecdc1c057e4c70ecd66151987296a/base/allocator/partition_allocator/)
and [public CEF](https://github.com/chromiumembedded/cef/tree/a5d51ba9db7ee74a523dc247bd09ec91ba4d7446).

## Patch behavior

`0001-win64-partitionalloc-4gib-pools.patch` selects 4 GiB only for
`IS_WIN && ARCH_CPU_X86_64`. The regular and BRP pool masks, allocation
bitmaps, reservation offset tables and configurable-pool upper limit derive
from the same `kPoolMaxSize` constant. The resulting pool has 2048 superpages
of 2 MiB each. The BRP forbidden zone remains part of address-space setup.

For two allocator instances, each containing a regular and BRP pool, the
maximum pool reservation changes from 64 GiB to 16 GiB, plus guards. This
calculation covers those four pools. V8, Blink and other reservations need
separate measurement. Smaller pools also reduce allocator capacity and
require browser workload testing for exhaustion.

Apply from the Chromium `src` directory, using the actual mdeck path on the
build machine.

```sh
git apply --check /path/to/mdeck/build/cef-patches/0001-win64-partitionalloc-4gib-pools.patch
git apply /path/to/mdeck/build/cef-patches/0001-win64-partitionalloc-4gib-pools.patch
```

Every component embedding PartitionAlloc, including `libcef.dll` and
`chrome_elf.dll`, must be rebuilt from the same patched headers.

## Component verification

The host regression extracts the actual pinned constant selector, masks,
metadata lengths, `AddressPoolManager::Pool` class and its eight allocation
methods. It substitutes host mutexes and assertions for Chromium infrastructure.
ASan/UBSan runs cover boundaries, exhaustion, release/reuse, requested
addresses, four independent pools and 10,000 randomized operations per
configuration. Seven selector configurations cover Windows x64, Windows
ARM64, desktop, Android, iOS and pointer compression.

```sh
python3 tests/host/check-cef-small-pools.py /path/to/patched/chromium/src
python3 tests/host/check-cef-small-pools.py /path/to/unmodified/chromium/src --baseline
```

An optional Windows x64 compiler also compiles the complete production
`address_pool_manager.cc`, `partition_address_space.cc` and
`reservation_offset_table.cc`, plus static assertions using their actual
headers. This uses explicitly documented fixture build flags, including
BRP and GWP-ASan, with the remaining discovered flags disabled. Production
CEF GN flags still require their own build.

```sh
python3 tests/host/check-cef-small-pools.py /path/to/patched/chromium/src \
  --windows-cxx /path/to/x86_64-w64-mingw32-clang++
```

These tests exercise pool algorithms and Windows target compilation. OS
virtual reservations, Windows execution, the complete CEF DLLs and iPad
Steam execution remain untested.

## Valve compatibility audit on 2026-11-27

The downloaded Steam win64 manifest has version `1794536281`. Its CEF
package is `bins_cef_win64.zip.c5d42279d6cd6d180eafa9297eddcf77badc871a`.
The archive SHA-256 matches the manifest value
`2e6056fc7f8f23b7703b2e5dd4fd4cfdaf17942349afc58094e1c00f250ddcee`.

| File | Observed version or identity | SHA-256 |
| --- | --- | --- |
| Current `libcef.dll` | `126.0.0-HEAD.3183+g659afd3+chromium-126.0.6478.183` | `6a634357cc37083902216adea2dfc65208e03ac06c07835477eeb130c8f887c2` |
| Current `chrome_elf.dll` | `126.0.6478.183`, Chromium `2e81dea53f5ecdc1c057e4c70ecd66151987296a` | `d336f4944bb2442cbe0b66435d77f16e96c5f7c34894d5da8d89248048414fc3` |
| Current `steamwebhelper.exe` | `11.23.65.88` | `e7ae397d5919d330c10dcc9ba00899726b33c07a657f02282a16686196978180` |
| Earlier reference `libcef.dll` | `126.0.0-HEAD.3171+gbbb7596+chromium-126.0.6478.183` | `c85bf94462b3c79baeac63823db52d15e116eead71ea414e5d3a112c59e434d3` |

All three current binaries have PE Machine `0x8664`. Current libcef exports
222 symbols. All 79 libcef functions imported by the current helper are
present in the current Valve libcef. Eight imported names are absent from
all headers in the pinned public CEF comparison tree.

```text
cef_generate_gpu_report
cef_get_device_scale_factor_for_screen_rect
cef_is_gpu_compositing_disabled
cef_is_hardware_acceleration_enabled
cef_set_force_device_scale_factor
cef_set_minimum_font_size
cef_set_preferred_contrast
cef_set_reduced_motion_enabled
```

The public CEF GitHub commit API returned HTTP 422 for both `659afd3` and
`bbb7596`. Matching Valve source changes have yet to be obtained. Export
presence alone also leaves C API structure layout and callback compatibility
unverified.

The follow-up binary/header audit confirmed that the helper checks Valve's
Windows API hash before initialization. It also found an actual structure-size
difference: public Windows x64 `cef_browser_settings_t` is 264 bytes, while
both Valve browser-creation entry points require 272 bytes. The audit script,
RVA evidence, exact hashes and reproduction instructions are documented in
[valve-abi-audit.md](valve-abi-audit.md).

The read-only follow-up on the paired Valve DLLs located their pool
initializers, dynamic capacities, inlined masks, offset-table examples and
VirtualAlloc calls. It also records why changing only the initial pool size
leaves incorrect membership tests. The feasibility checklist and the bounded
instruction inventory are documented in
[valve-binary-pool-audit.md](valve-binary-pool-audit.md).

A follow-up generated an experimental `chrome_elf.dll` with 105 recorded
edits and executed its allocator, reservation and scanner components. The
native scalar/SSE4.1 checks passed. AVX used explicit instruction emulation,
and Windows execution remains unverified. Reproduction, exact hashes,
metadata decisions and test coverage are documented in
[valve-elf-4gib-experiment.md](valve-elf-4gib-experiment.md).

The matching `libcef.dll` experiment adds 31715 recorded edits. Both generated
DLLs are in `outputs/cef-pair-4gib-experiment/`. Their original/patched allocator,
reservation and scanner component tests passed. The libcef mask geometry
check covers 761016 boundary cases, while full Windows and Steam execution
remain unverified. The hashes, four preserved scalar constants, reproduction
commands and execution limits are documented in
[valve-pair-4gib-experiment.md](valve-pair-4gib-experiment.md).

Valve artifacts were retrieved from the
[Steam update CDN](https://client-update.akamai.steamstatic.com/steam_client_win64).

## Remaining build and execution work

A complete Chromium/CEF checkout and configured Windows Chromium toolchain
are still needed for the unmodified CEF control build and paired patched
DLL build. The local llvm-mingw compiler used above successfully compiles
the allocator components. It has not built the complete CEF targets.

In a configured Windows CEF tree, `cef_create_projects.bat` generates the
GN configurations and `autoninja -C out/Release_GN_x64 cef` builds the
public CEF group, including its clients and tests. Keep control and patched
artifacts separate and compare actual reservations during execution. These
full-build commands have not been executed in this experiment.

Replacing Valve CEF through a public-source rebuild still needs matching
implementations and ABI verification for Valve's custom interfaces. The
binary experiment uses Valve's fixed pair and preserves its existing
interface bytes. Actual DLL loading and browser execution must establish
runtime compatibility. Compare startup, renderer creation, pool exhaustion
and shutdown on Windows, then Wine/FEX and iPad. The generated pair has not
been included in an IPA.
