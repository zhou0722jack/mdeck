# Valve chrome_elf 4 GiB binary experiment

An experimental Windows x64 `chrome_elf.dll` has been generated from the
hash-pinned Valve binary. Its pool initializer requests 4 GiB regular and
BRP pools. The experiment also updates address classification and PCScan
indexing used with those pools.

## Artifacts and reproduction

The generated files are in `outputs/cef-elf-4gib-experiment/`.

| File | Purpose |
| --- | --- |
| `chrome_elf.dll` | Experimental binary, 1,394,176 bytes |
| `patch-manifest.json` | Every edit's RVA, file offset, old/new bytes and classification evidence |
| `verification.json` | Executed checks and execution limitations |

The original binary's SHA-256 is
`d336f4944bb2442cbe0b66435d77f16e96c5f7c34894d5da8d89248048414fc3`.
The generated binary's SHA-256 is
`6d438bfe32084eb14c55bd5a5508f7e4dfb6054ccff2f97d5f18ac4b72927d9e`.

Install `pefile`, `capstone` and `unicorn==2.1.4` in the Python environment
used to run the tools. From the repository root, generate into a fresh output
directory and execute the component checks.

```sh
python3 tools/cef/patch-valve-elf-pools.py /path/to/original/chrome_elf.dll \
  outputs/cef-elf-4gib-experiment
python3 tests/host/check-cef-elf-binary.py /path/to/original/chrome_elf.dll \
  outputs/cef-elf-4gib-experiment/chrome_elf.dll \
  --report outputs/cef-elf-4gib-experiment/verification.json
```

The test's native scanner stage uses Clang and an x86_64 macOS executable.
On the current Apple Silicon Mac, Rosetta executes the scalar and SSE4.1
scanner bodies. CPUID reports AVX2 unavailable in that environment.

The generator rejects another source hash, unexpected instruction boundaries,
unexpected bytes, overlapping edits and existing output files. It verifies
that all modified bytes belong to the manifest or the explicitly recorded PE
checksum and certificate fields.

## The 105 binary edits

| Change | Count | Evidence or behavior |
| --- | --- | --- |
| Scalar pool masks | 99 | `0xfffffffc00000000` becomes `0xffffffff00000000` |
| Pool initializer size and alignment | 1 | Immediate at RVA `0x41805` changes 16 GiB to 4 GiB |
| PCScan card indices | 3 | Immediate at instruction RVAs `0xe3794`, `0xe49b3`, `0xe59de` changes `0x1fffff` to `0x7ffff` |
| AVX2 broadcast mask | 1 | 64-bit constant at RVA `0x10f358` |
| SSE4.1 packed mask | 1 | Four bytes at RVA `0x10f360` change `00fc00fc` to `00ff00ff` |

Scalar mask instructions were decoded from their containing unwind-function
ranges, plus the independently identified PCScan leaf range
`0xe3780`–`0xe37d8`. The classification has 70 masks in functions referencing
the BRP pool, 25 in functions referencing both pools, three in regular-pool
scanner functions and one in the PCScan card-table leaf. Regular and BRP
global slots are at RVAs `0x13ae80` and `0x13ae88`.

Each scalar entry records the pool-reference instructions and its following
instruction context. This establishes function-level classification.
Execution coverage below applies to the tested routines, and full data-flow
proof for every path through all 99 sites remains open.

## Metadata and PCScan decisions

The binary experiment keeps the existing Pool stride of `0x420`, its physical
8192-bit bitmap and the reservation-offset table stride of `0x4000`. The
actual capacity is computed from the pool length, so 4 GiB uses 2048
superpages. The extra physical metadata stays allocated.

PCScan keeps 8 KiB cards and its physical 2 MiB table. The three index masks
select the lower 512 KiB of that table for a 4 GiB pool. Card readers and
writers retain their matching shift of 13 and existing range lengths. A
source rebuild with `kPoolMaxSize=4 GiB` would derive a different card size.
The preserved-card choice is specific to this binary experiment.

The original Valve Authenticode certificate is removed, its security-directory
entry is cleared and the PE checksum is recalculated. The resulting binary
has no Valve signature. The manifest records the removed certificate's
offset, size and digest.

## Verification results

Both original and patched DLL instructions were exercised for comparison.

| Check | Result |
| --- | --- |
| Reproducing the exact patched binary and rejecting a changed input | Passed |
| All 99 scalar mask values at four aligned pool placements and six boundary addresses | 2376 checks passed |
| Actual Pool initialization, allocation, requested addresses, exhaustion, free and reuse | Passed for 16 GiB original and 4 GiB patched pools |
| Random allocation/free sequences against an independent occupancy model | 1200 operations per binary passed |
| Actual reservation wrapper through its VirtualAlloc import | Passed with a mocked Windows OS service |
| Three failed reservation attempts followed by oversized reservation, release and final aligned reservation | Passed for regular and BRP pools in both binaries |
| PCScan's three real card-index instruction sequences | 84 boundary checks passed |
| PCScan card lookup/clear and preserved reservation-offset table stride | Passed |
| Actual scalar and SSE4.1 scanner bodies in an x86_64 macOS executable | 256 cases per binary passed |
| Actual AVX scanner control flow with explicit vector-instruction emulation | 128 cases per binary passed |
| Restoring the old SSE or AVX mask as negative controls | Each defective variant was detected |

The emulated allocator executes the DLL's real x86 instructions. Windows
reservation, decommit, SRW-lock operations and selected CRT services are
fixtures. These tests inspect reservation arguments and allocator state,
without allocating a real 4 GiB Windows address range or testing concurrent
Windows threads.

The native scanner harness executes the supplied DLL's original scanner
bodies and constants. It substitutes the PCScan mark callback to observe
candidate selection without constructing a complete CEF heap. This covers
vector iteration, scalar tails and pool boundaries.

Unicorn 2.1.4 rejects the AVX instructions. The AVX test therefore executes
the scanner's general control flow in Unicorn and interprets its ten vector
operation kinds explicitly. This validates the selected candidates and mask
data under that model. Native AVX2 execution remains unverified.

The reservation fallback can temporarily request `2 * pool_size - 64 KiB`
for a regular pool, or `2 * pool_size` for a BRP pool. A 4 GiB pool therefore
still has a nearly 8 GiB temporary alignment-reservation path.

## Remaining acceptance

Windows DLL loading, complete DLL startup, complete PCScan operation,
concurrent allocator behavior and Steam/iPad execution remain unverified.
The subsequent paired libcef experiment and its component verification are
documented in [valve-pair-4gib-experiment.md](valve-pair-4gib-experiment.md).
This document records the chrome_elf component experiment and its tools.
