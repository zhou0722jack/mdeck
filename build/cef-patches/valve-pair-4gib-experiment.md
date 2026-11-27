# Valve CEF paired 4 GiB binary experiment

The paired experiment contains hash-pinned Valve Windows x64 `libcef.dll`
and `chrome_elf.dll` copies with 4 GiB regular and BRP allocator pools.
Both copies and their individual edit manifests and component reports are in
`outputs/cef-pair-4gib-experiment/`.

| File | Bytes | SHA-256 |
| --- | --- | --- |
| `libcef.dll` | 219851776 | `ada0ff25bc252e176b6c80aee6834ccfc9a2cf3c3082beda61a34f23c698d34b` |
| `chrome_elf.dll` | 1394176 | `6d438bfe32084eb14c55bd5a5508f7e4dfb6054ccff2f97d5f18ac4b72927d9e` |

The source `libcef.dll` is Valve's
`126.0.0-HEAD.3183+g659afd3+chromium-126.0.6478.183`, with SHA-256
`6a634357cc37083902216adea2dfc65208e03ac06c07835477eeb130c8f887c2`.
The matching source `chrome_elf.dll` has SHA-256
`d336f4944bb2442cbe0b66435d77f16e96c5f7c34894d5da8d89248048414fc3`.
Both came from the same downloaded Valve CEF package described in README.md.

The `libcef-patch-manifest.json` records the libcef changes. The
`patch-manifest.json` records chrome_elf changes and describes that generator's
individual component scope. The complete folder contains both generated DLLs.
`libcef-verification.json` and `chrome-elf-verification.json` record each
DLL's executed checks. `libcef-abi-verification.json` records the patched
library's static comparison with the matching Steam helper.

The output DLLs have their original Authenticode certificates removed and
their PE checksums recalculated. They carry no Valve digital signature.

## Automatic installation in mdeck

The app bundles `BundledInstallers/SteamCEF4GiB.json`, a 301729-byte recipe
containing the verified input/output hashes and grouped byte edits for this
pair. `SteamCEFPoolPatch.swift` applies it to the installed files using
streamed IO. Generate the recipe from the original pair and the reproduced
experiment outputs with

```sh
python3 tools/cef/bundle-steam-pool-patches.py /path/to/originals \
  outputs/cef-pair-4gib-experiment \
  app/Madeira/BundledInstallers/SteamCEF4GiB.json
```

The normal Wine child-creation path calls the app before starting the x64
`Program Files/Steam Client/bin/cef/cef.win64/steamwebhelper.exe`. This catches
the first CEF launch after Steam's updater installs its packages, and later
launches following an update. The resolved app install path and the helper's
x64 PE header must match. Unknown DLL hashes keep the installed pair and
produce an `unsupported CEF version` log entry.

The patcher saves hash-verified originals under the CEF directory's
`.mdeck-cef-4gib` folder, stages and verifies both outputs, and writes a durable
transaction journal before replacing either file. Errors restore the previous
pair. An abrupt app exit leaves a journal that the next helper launch recovers.
An unrecoverable transaction stops that helper launch and logs the failure.
In-process and file locks serialize concurrent helper starts. Subsequent starts
reuse the successful verification while inode, size and nanosecond modification
and change times of both DLLs and the recipe match.

The host regression runs small deterministic transaction fixtures by default.
Its optional real-DLL mode checks the original Valve pair against the bundled
recipe and verifies exact experiment output hashes. Both modes cover repeated
launches, full and partial updater replacement, in-place file changes, rollback,
abrupt exit followed by recovery in another OS process, concurrent starts,
unknown versions, damaged backups and path/architecture exclusions.

```sh
python3 tests/host/check-steam-cef-patch.py
python3 tests/host/check-steam-cef-patch.py \
  --originals /path/to/originals --helper /path/to/paired/steamwebhelper.exe
```

These host tests exercise file installation and the Wine spawn hook. Complete
CEF execution, Steam page rendering and on-device performance await runtime
testing with the installed pair.

## Reproduction

Use a Python environment containing `pefile`, `capstone`, and
`unicorn==2.1.4`. Native scanner tests require Clang, macOS x86_64 execution,
and SSE4.1. The current Apple Silicon Mac runs that harness through Rosetta.
Run from the repository root and choose a fresh output directory.

```sh
python3 tools/cef/patch-valve-libcef-pools.py /path/to/original/libcef.dll \
  outputs/cef-pair-4gib-experiment
python3 tools/cef/patch-valve-elf-pools.py /path/to/original/chrome_elf.dll \
  outputs/cef-pair-4gib-experiment
python3 tests/host/check-cef-elf-binary.py /path/to/original/libcef.dll \
  outputs/cef-pair-4gib-experiment/libcef.dll --library libcef \
  --report outputs/cef-pair-4gib-experiment/libcef-verification.json
python3 tests/host/check-cef-elf-binary.py /path/to/original/chrome_elf.dll \
  outputs/cef-pair-4gib-experiment/chrome_elf.dll \
  --report outputs/cef-pair-4gib-experiment/chrome-elf-verification.json
python3 tools/cef/audit-steam-abi.py \
  --helper /path/to/paired/steamwebhelper.exe \
  --libcef outputs/cef-pair-4gib-experiment/libcef.dll \
  --cef-root /path/to/pinned/public/cef \
  > outputs/cef-pair-4gib-experiment/libcef-abi-verification.json
```

The libcef generator rejects a different source digest, unexpected instruction
boundaries or operand kinds, overlapping edits, unexpected source bytes,
unclassified scalar masks, and existing output files. Every changed byte must
belong to its edit manifest, checksum, or certificate directory. The original
input is read only.

## libcef changes

| Change | Count | Location or behavior |
| --- | --- | --- |
| Scalar pool masks | 31709 | `0xfffffffc00000000` becomes `0xffffffff00000000` |
| Pool size and alignment | 1 | Immediate at RVA `0x1421575` changes 16 GiB to 4 GiB |
| PCScan card index masks | 3 | Instructions at `0x74f6f24`, `0x74f80f3`, `0x74f9a1e` use `0x7ffff` |
| AVX broadcast mask | 1 | Constant at `0xc0807c0` |
| SSE sign-extended packed mask | 1 | Constant at `0xc0807c8` changes `00fc00fc` to `00ff00ff` |
| Total | 31715 | PE checksum and removed signature are recorded separately |

The 31709 scalar instructions occur in 29413 containing function ranges,
including the separately identified PCScan leaf. Full-function decoded RIP
references identify the regular slot at `0xc9766c0` and BRP slot at
`0xc9766c8`. The classifications are 31649 BRP, 56 both pools, three regular,
and one PCScan card-table/membership instruction. Each manifest edit includes
its instruction context, and each function record includes its pool references.
Function-level classification leaves full data-flow proof for every path open.

Four other occurrences of the same scalar constant are preserved after
reviewing their surrounding instructions.

| Instruction RVA | Observed surrounding operation |
| --- | --- |
| `0x6b868ab` | Integer transform adds `0x300000000` and reconstructs 32-bit halves |
| `0x7a842f0` | Arithmetic value construction following a 32-bit shift |
| `0x8646386` | Constructor stores the literal in a stack record |
| `0xae531e7` | Integer loop-bound calculation adds the literal before a shift by 32 |

The generator requires exactly these four old scalar constants to remain in
executable sections. Other subsystems' 16 GiB constants and offset masks are
preserved. The existing chrome_elf generator produces the same 105-edit
binary and SHA-256 as its earlier standalone experiment.

## Metadata decisions

Both binary patches retain the original Pool stride of `0x420`, 8192-bit
physical bitmap, and reservation-offset-table stride of `0x4000`. Runtime
capacity derives from the pool length, giving 2048 superpages per 4 GiB pool.
The extra physical metadata remains allocated.

PCScan retains its 8 KiB card size and physical 2 MiB table. Its updated index
masks address the lower 512 KiB for a 4 GiB pool. This preserves the existing
binary shifts and layouts. The separate Chromium source patch derives its
card geometry from source constants and has a different implementation.

## Component verification

Each DLL's original 16 GiB and patched 4 GiB instructions were tested.

| Check | libcef result | chrome_elf result |
| --- | --- | --- |
| Exact reproduction and changed-input rejection | Passed | Passed |
| Scalar mask geometry at four placements and six boundary offsets | 761016 checks passed | 2376 checks passed |
| Initialization, pool capacity, requested address, exhaustion, free/reuse | Passed | Passed |
| Random allocation/free sequences against an independent occupancy model | 1200 operations per binary passed | 1200 operations per binary passed |
| Real reservation-wrapper instructions with mocked VirtualAlloc | Passed | Passed |
| Three failed reservations, oversized reservation, release, aligned retry | Regular and BRP passed | Regular and BRP passed |
| Real card-index instruction fragments, lookup/clear, offset-table access | 84 index checks passed | 84 index checks passed |
| Native scalar/SSE scanner bodies and scalar tails | 256 cases per binary passed | 256 cases per binary passed |
| Real AVX control flow with explicit vector semantics | 128 cases per binary passed | 128 cases per binary passed |
| Missing SSE/AVX mask negative controls | Detected | Detected |
| PE machine, entry point, image geometry and section headers | Preserved | Preserved |
| Import/export, exception, resource and other populated directory bytes | Preserved | Preserved |

The patched libcef retains all 222 exports and satisfies all 79 imports from
the paired Steam helper. Its Valve Windows API hash remains
`0755a0099cb84cb99d91b47ab7b616435f207952`, matching all four recognized helper
hash checks. Its settings-size checks retain 448-byte initialization settings
and 272-byte browser settings. These static checks establish the observed
interface identities. Runtime interaction with the helper remains unverified.

The allocator test runs real DLL x86 instructions in Unicorn while replacing
Windows reservations, SRW locks, decommit, a random-address hint and selected
CRT services. Mask geometry checks inspect every changed mask value.
Execution tests cover the listed allocator and scanner routines. The tests
do not execute all 31709 scalar sites or exercise concurrent Windows threads.

Native scalar/SSE checks execute the DLL's scanner instructions and constants
inside an x86_64 macOS harness. The complex PCScan marking callback is replaced
to observe the selected candidates. AVX2 is unavailable in the current native
environment, and Unicorn 2.1.4 rejects these instructions. The AVX check uses
explicit semantics for its ten vector operation kinds with Unicorn executing
the surrounding control flow. Native AVX2 execution remains unverified.

The fallback reservation path still temporarily requests up to
8589869056 bytes for a regular pool or 8589934592 bytes for a BRP pool.
These near-8 GiB temporary ranges must be measured on the target runtime.

Complete Windows DLL loading and initialization, browser creation, complete
PCScan, concurrent allocator behavior, Steam, Wine/FEX, and iPad execution
remain unverified. The pair has not been installed in mdeck or packaged into
an IPA. The next execution comparison uses the original Valve pair as the
control and these matching patched DLLs as the experiment.
