# Valve Windows x64 CEF ABI audit

Observed on 2026-11-27. The binary identities and source pins are recorded in
[README.md](README.md). The audit uses static PE inspection, bounded getter
decoding and Windows x64 header compilation. It does not execute Steam or CEF.

## Confirmed differences

The current Valve `libcef.dll` exports 222 named symbols. The paired Steam
helper imports 79 of them, all present in that DLL. Eight imported names are
absent from the pinned public CEF headers. Their names are listed in the README.

The interface hashes also differ.

| API identity | Valve DLL | Public CEF comparison tree |
| --- | --- | --- |
| Windows | `0755a0099cb84cb99d91b47ab7b616435f207952` | `0d99d1b9b85b2efab91a39d6fc325bb6d56fd524` |
| Universal | `4b25ee013e788dac1948132d2f2cf1ec6ba9d01b` | `ed1dfa5ff8a041241f8fb72eb7454811f358f0d3` |

The Valve getter returns the full CEF commit
`659afd3a1389ed2f166a38d6d57b4588faf128eb` for `cef_api_hash(2)`.
The public comparison tree is
`a5d51ba9db7ee74a523dc247bd09ec91ba4d7446`. Both use Chromium
`126.0.6478.183`.

There is a concrete structure-size difference as well.

| Structure | Public Windows x64 header size | Valve DLL required size |
| --- | --- | --- |
| `cef_settings_t` | 448 | 448 |
| `cef_browser_settings_t` | 264 | 272 |

Public sizes come from compiling the actual public C headers with
llvm-mingw Clang 22.1.4 for Windows x64. The generated `cef_config.h` represents
Windows with Alloy enabled. `net/base/net_error_list.h` is taken from Chromium
commit `2e81dea53f5ecdc1c057e4c70ecd66151987296a` to satisfy the source headers'
include dependency.

The size equality for `cef_settings_t` establishes its total size only. Field
offsets, semantics and callback layouts still require Valve-specific evidence.
The additional bytes in Valve's browser settings have yet to be identified.

## Binary evidence

Addresses below are RVAs relative to each PE image base. They apply to the
exact binaries identified by SHA-256 in the README and generated JSON report.

In `steamwebhelper.exe`, `cef_api_hash` uses an import thunk at RVA `0x37527c`.
Four direct call sites load the same expected Windows hash immediately after
calling that thunk.

```text
0x2da4ba
0x2da67b
0x2e13ab
0x2e165b
```

The initialization wrapper beginning at RVA `0x2da650` sets ECX to zero and
calls `cef_api_hash` at `0x2da67b`. It loads the expected hash at `0x2da680`,
then calls the string comparison routine at `0x486770`. The routine compares
the strings byte by byte and returns zero for equality. At `0x2da694`, equality
branches to `0x2da6b4`. The mismatch path clears AL at `0x2da6b0` and returns
without reaching the `cef_initialize` import call at `0x2da6f0`.

The public wrapper has corresponding hash guards in `CefExecuteProcess` and
`CefInitialize` in `libcef_dll/wrapper/libcef_dll_wrapper.cc`.

The current Valve DLL has these explicit settings-size checks.

```text
cef_initialize                       RVA 0x27640d  cmpq $0x1c0, (%r15)
cef_browser_host_create_browser      RVA 0x27dca8  cmpq $0x110, (%r12)
cef_browser_host_create_browser_sync RVA 0x27e036  cmpq $0x110, (%r12)
```

The first uses the settings pointer retained from the initialization argument.
The browser entry points retain the fourth argument in R12. Those browser
entry points reject a size other than 272 before proceeding with creation.

## Reproduction

`tools/cef/audit-steam-abi.py` requires `pefile` in its Python environment.
It reads the supplied PE files, uses the supplied public CEF tree's own
`cef_api_hash` calculator and optionally compiles its real headers. The getter
decoder and instruction recognizers accept the audited revision's instruction
forms. Unrecognized forms cause an error and need another disassembly review.

```sh
python3 tools/cef/audit-steam-abi.py \
  --helper /path/to/paired/steamwebhelper.exe \
  --libcef /path/to/paired/libcef.dll \
  --cef-root /path/to/public/cef \
  --chromium-root /path/to/pinned/chromium/src \
  --windows-cxx /path/to/x86_64-w64-mingw32-clang++ \
  > /path/to/audit.json
```

Omitting the compiler and Chromium options runs the import/hash audit alone.
The full audit includes layouts for seven public structures and records the
observed size comparisons. The local generated report is
`outputs/cef-steam-abi-20261127.json`.

## Source availability and build status

The matching Valve commit, generated headers, Chromium/CEF patches and GN
configuration have not been located in the searched public sources. The public
source request remains open. As checked on 2026-11-27, its single comment asks
for matching CEF 126 sources and headers and contains no Valve source link.

[Valve source request](https://github.com/ValveSoftware/steam-for-linux/issues/12226)

The current 4 GiB change has component-level verification. A compatible control
DLL pair and a patched DLL pair have yet to be built. The local environment
contains the allocator subset and llvm-mingw cross compiler. It lacks a complete
configured Chromium checkout and Windows CEF build toolchain. Chromium's native
build dependencies and toolchain need to be provisioned for the full build.

The unresolved compatibility work includes the eight custom functions' complete
signatures and behavior, Valve's browser-settings layout, and remaining C API
structures and callbacks. Matching headers/source, or an independently verified
implementation of those interfaces, is needed to validate a compatible control.
Steam library startup and actual pool reservation measurements remain pending.
