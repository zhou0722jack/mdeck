#!/usr/bin/env python3
"""Inspect Windows x64 Steam/CEF compatibility without executing either PE file.

Requires pefile. Public API hashes come from the supplied CEF tree's own
calculator. Optional layout compilation uses that tree's actual C headers.
"""

import argparse
import hashlib
import importlib
import json
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import pefile
except ImportError:
    sys.exit("Install pefile in the Python environment used for this audit.")


def load_pe(path):
    pe = pefile.PE(str(path), fast_load=True)
    if pe.FILE_HEADER.Machine != 0x8664:
        raise ValueError(f"{path} is not Windows x64")
    pe.parse_data_directories(directories=[0, 1, 13])
    return pe


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest()}


def exports(pe):
    return {
        symbol.name.decode("ascii"): symbol.address
        for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols
        if symbol.name
    }


def cef_imports(pe):
    result = {}
    for directory in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
        for library in getattr(pe, directory, []):
            if library.dll.lower() != b"libcef.dll":
                continue
            for symbol in library.imports:
                if not symbol.name:
                    raise ValueError("Ordinal libcef imports need a separate audit")
                result[symbol.name.decode("ascii")] = symbol.address
    if not result:
        raise ValueError("No libcef.dll imports found in Steam helper")
    return result


def api_hash(pe, start, entry):
    # Decode only the small, side-effect-free getter present in this Valve
    # revision. Reject unfamiliar instructions instead of guessing their effect.
    pc = start
    equal = False
    result = None
    for _ in range(32):
        if not start <= pc < start + 256:
            raise ValueError("cef_api_hash branches outside its bounded getter")
        code = pe.get_data(pc, 7)
        if code.startswith(b"\x85\xc9"):
            equal = entry == 0
            pc += 2
        elif code.startswith(b"\x83\xf9"):
            equal = entry == code[2]
            pc += 3
        elif code[0] in (0x74, 0x75):
            take = equal if code[0] == 0x74 else not equal
            pc += 2 + (struct.unpack("b", code[1:2])[0] if take else 0)
        elif code.startswith(b"\x48\x8d\x05"):
            result = pc + 7 + struct.unpack("<i", code[3:7])[0]
            pc += 7
        elif code.startswith(b"\x31\xc0"):
            result = None
            pc += 2
        elif code[0] == 0xC3:
            if result is None:
                return None
            value = pe.get_string_at_rva(result).decode("ascii")
            if not re.fullmatch(r"[0-9a-f]{40}", value):
                raise ValueError("cef_api_hash returned an unexpected string")
            return value
        else:
            raise ValueError(f"Unsupported cef_api_hash instruction at RVA {pc:#x}")
    raise ValueError("cef_api_hash getter exceeded the instruction bound")


def helper_hash_references(pe, iat_address):
    base = pe.OPTIONAL_HEADER.ImageBase
    sections = [section for section in pe.sections if section.Characteristics & 0x20000000]
    thunks = set()
    for section in sections:
        data = section.get_data()
        for offset in range(len(data) - 5):
            if data[offset:offset + 2] != b"\xff\x25":
                continue
            address = base + section.VirtualAddress + offset
            target = address + 6 + struct.unpack_from("<i", data, offset + 2)[0]
            if target == iat_address:
                thunks.add(address)
    references = []
    for section in sections:
        data = section.get_data()
        for offset in range(len(data) - 15):
            if data[offset] != 0xE8:
                continue
            address = base + section.VirtualAddress + offset
            target = address + 5 + struct.unpack_from("<i", data, offset + 1)[0]
            if target not in thunks:
                continue
            following = data[offset + 5:offset + 15]
            # This revision loads the expected hash into RDX immediately after
            # the getter call, then moves the returned pointer from RAX to RCX.
            if following[:3] != b"\x48\x8d\x15" or following[7:] != b"\x48\x8b\xc8":
                continue
            string_rva = address - base + 12 + struct.unpack("<i", following[3:7])[0]
            value = pe.get_string_at_rva(string_rva).decode("ascii")
            if re.fullmatch(r"[0-9a-f]{40}", value):
                references.append({"call_rva": hex(address - base), "expected_hash": value})
    if not references:
        raise ValueError("No recognized helper API hash references found")
    return references


def public_hashes(cef_root):
    sys.path.insert(0, str(cef_root / "tools"))
    calculator = importlib.import_module("cef_api_hash").cef_api_hash
    return calculator(str(cef_root / "include")).calculate()


def valve_size_checks(pe, symbols):
    checks = {}
    # These exact instructions compare the size field of the settings pointer
    # retained in R15 (initialization) or R12 (browser creation). Their function
    # context is independently checked in the accompanying disassembly report.
    for name, structure, opcode in (
        ("cef_initialize", "_cef_settings_t", b"\x49\x81\x3f"),
        ("cef_browser_host_create_browser", "_cef_browser_settings_t", b"\x49\x81\x3c\x24"),
        ("cef_browser_host_create_browser_sync", "_cef_browser_settings_t", b"\x49\x81\x3c\x24"),
    ):
        start = symbols[name]
        code = pe.get_data(start, 256)
        matches = list(re.finditer(re.escape(opcode) + b"(.{4})", code, re.DOTALL))
        if len(matches) != 1:
            raise ValueError(f"Unrecognized {name} settings-size check")
        match = matches[0]
        checks[name] = {
            "structure": structure,
            "size_check_rva": hex(start + match.start()),
            "required_size": struct.unpack("<I", match.group(1))[0],
        }
    return checks


def public_layouts(cef_root, chromium_root, compiler):
    names = {
        "_cef_settings_t", "_cef_browser_settings_t", "_cef_app_t",
        "_cef_client_t", "_cef_browser_process_handler_t",
        "_cef_render_process_handler_t", "_cef_window_info_t",
    }
    with tempfile.TemporaryDirectory(prefix="mdeck-cef-layout-") as temporary:
        root = Path(temporary)
        (root / "include").mkdir()
        # Windows, Alloy enabled. The public generator emits no platform
        # defines for this configuration. No CEF source files are modified.
        (root / "include/cef_config.h").write_text("#pragma once\n")
        source = root / "layouts.c"
        source.write_text(
            '#if !defined(_WIN64) || !defined(__x86_64__)\n'
            '#error Windows x64 target required\n'
            '#endif\n'
            '#include "include/capi/cef_app_capi.h"\n'
            '#include "include/capi/cef_client_capi.h"\n'
            '#include "include/capi/cef_browser_capi.h"\n'
        )
        result = subprocess.run(
            [str(compiler), "-x", "c", "-fsyntax-only", "-I", str(root),
             "-I", str(cef_root), "-I", str(chromium_root), "-Xclang",
             "-fdump-record-layouts-complete", str(source)],
            capture_output=True, text=True, check=True,
        )
    layouts = {}
    for block in result.stdout.split("*** Dumping AST Record Layout"):
        declaration = re.search(r"^\s*0 \| struct (\w+)\s*$", block, re.MULTILINE)
        size = re.search(r"\[sizeof=(\d+), align=(\d+)\]", block)
        if declaration and declaration.group(1) in names and size:
            layouts[declaration.group(1)] = {
                "size": int(size.group(1)), "alignment": int(size.group(2)),
                "layout": block.strip(),
            }
    if set(layouts) != names:
        raise ValueError(f"Missing CEF layouts: {sorted(names - set(layouts))}")
    return layouts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--libcef", type=Path, required=True)
    parser.add_argument("--cef-root", type=Path, required=True)
    parser.add_argument("--chromium-root", type=Path)
    parser.add_argument("--windows-cxx", type=Path)
    args = parser.parse_args()
    if args.windows_cxx and not args.chromium_root:
        parser.error("--windows-cxx requires --chromium-root for CEF's Chromium includes")
    library = load_pe(args.libcef)
    helper = load_pe(args.helper)
    symbols = exports(library)
    imported = cef_imports(helper)
    hashes = public_hashes(args.cef_root)
    valve_hashes = {
        name: api_hash(library, symbols["cef_api_hash"], entry)
        for entry, name in enumerate(("windows", "universal", "cef_commit"))
    }
    references = helper_hash_references(helper, imported["cef_api_hash"])
    public_headers = "\n".join(
        path.read_text() for path in sorted((args.cef_root / "include").rglob("*.h"))
    )
    report = {
        "helper": fingerprint(args.helper), "libcef": fingerprint(args.libcef),
        "helper_import_count": len(imported), "libcef_export_count": len(symbols),
        "imports_missing_from_valve_dll": sorted(set(imported) - set(symbols)),
        "import_names_absent_from_public_headers": [
            name for name in sorted(imported)
            if not re.search(r"\b" + re.escape(name) + r"\b", public_headers)
        ],
        "valve_api_hashes": valve_hashes, "public_api_hashes": hashes,
        "helper_hash_references": references,
        "valve_settings_size_checks": valve_size_checks(library, symbols),
        "helper_hashes_match_valve": all(
            item["expected_hash"] == valve_hashes["windows"] for item in references
        ),
        "public_windows_hash_matches_valve": hashes["windows"] == valve_hashes["windows"],
        "execution_performed": False,
        "unverified": [
            "Valve custom function signatures and behavior",
            "Full Valve C API structure and callback layouts",
            "Compatible complete CEF build and Steam runtime behavior",
        ],
    }
    if args.windows_cxx:
        report["public_windows_layouts"] = public_layouts(
            args.cef_root, args.chromium_root, args.windows_cxx
        )
        for check in report["valve_settings_size_checks"].values():
            check["public_size"] = report["public_windows_layouts"][check["structure"]]["size"]
            check["public_size_matches"] = check["public_size"] == check["required_size"]
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
