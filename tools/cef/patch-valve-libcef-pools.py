#!/usr/bin/env python3
"""Generate the pinned Valve libcef.dll 4 GiB component experiment.

Requires pefile and capstone. Function-level pool references classify edits.
Four unrelated scalar constants and other subsystems' size constants are kept.
"""

import argparse
import bisect
from collections import Counter, defaultdict
import importlib.util
import json
from pathlib import Path
import struct

import capstone
import pefile


SOURCE_SHA256 = "6a634357cc37083902216adea2dfc65208e03ac06c07835477eeb130c8f887c2"
OLD_MASK = 0xFFFFFFFC00000000
NEW_MASK = 0xFFFFFFFF00000000
POOL_SLOTS = {0xC9766C0: "regular", 0xC9766C8: "brp"}
LEAF_RANGE = (0x74F6F10, 0x74F6F68)
EXCLUDED = {
    0x6B868AB: "Standalone integer transform, adds 0x300000000 and reconstructs 32-bit halves",
    0x7A842F0: "Arithmetic value construction, added after a 32-bit shift",
    0x8646386: "Data constructor, stores the literal to a stack record",
    0xAE531E7: "Integer loop-bound arithmetic, adds the literal before shifting right 32",
}


def load_elf_tool():
    path = Path(__file__).with_name("patch-valve-elf-pools.py")
    spec = importlib.util.spec_from_file_location("valve_elf_patch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_experiment(source):
    common = load_elf_tool()
    if common.digest(source) != SOURCE_SHA256:
        raise ValueError("Source SHA-256 differs from the pinned Valve libcef.dll")
    pe = pefile.PE(data=source, fast_load=True)
    pe.parse_data_directories(directories=[3])
    functions = sorted((item.struct.BeginAddress, item.struct.EndAddress)
                       for item in pe.DIRECTORY_ENTRY_EXCEPTION)
    starts = [start for start, end in functions]
    groups = defaultdict(list)
    seen_excluded = set()
    old_bytes = struct.pack("<Q", OLD_MASK)
    raw_count = 0
    for section in pe.sections:
        if not section.Characteristics & 0x20000000:
            continue
        data = section.get_data()
        offset = data.find(old_bytes)
        while offset >= 0:
            raw_count += 1
            rva = section.VirtualAddress + offset - 2
            if rva in EXCLUDED:
                seen_excluded.add(rva)
            elif LEAF_RANGE[0] <= rva < LEAF_RANGE[1]:
                groups[LEAF_RANGE].append(rva)
            else:
                index = bisect.bisect_right(starts, rva) - 1
                if index < 0 or rva + 10 > functions[index][1]:
                    raise ValueError(f"Unclassified mask at RVA {rva:#x}")
                groups[functions[index]].append(rva)
            offset = data.find(old_bytes, offset + 1)
    if raw_count != 31713 or seen_excluded != set(EXCLUDED):
        raise ValueError("Unexpected scalar-mask inventory")
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    patched = bytearray(source)
    edits = []
    occupied = set()
    classified_functions = []

    def change(rva, before, after, reason, **evidence):
        offset = pe.get_offset_from_rva(rva)
        touched = set(range(offset, offset + len(before)))
        if len(before) != len(after) or source[offset:offset + len(before)] != before:
            raise ValueError(f"Unexpected bytes at RVA {rva:#x}")
        if touched & occupied:
            raise ValueError(f"Overlapping edit at RVA {rva:#x}")
        occupied.update(touched)
        patched[offset:offset + len(after)] = after
        edits.append({"rva": hex(rva), "offset": offset, "before": before.hex(),
                      "after": after.hex(), "reason": reason, **evidence})

    for (start, end), sites in sorted(groups.items()):
        instructions = list(decoder.disasm(pe.get_data(start, end - start), start))
        boundaries = {item.address: position for position, item in enumerate(instructions)}
        references = {}
        for item in instructions:
            for operand in item.operands:
                if operand.type != capstone.x86.X86_OP_MEM or operand.mem.base != capstone.x86.X86_REG_RIP:
                    continue
                target = item.address + item.size + operand.mem.disp
                if target in POOL_SLOTS and target not in references:
                    references[target] = {"pool": POOL_SLOTS[target], "rva": hex(item.address),
                                          "instruction": f"{item.mnemonic} {item.op_str}"}
        if not references:
            raise ValueError(f"No classified pool reference in mask function {start:#x}")
        category = "+".join(sorted(POOL_SLOTS[target] for target in references))
        if start == LEAF_RANGE[0]:
            category = "pcscan-card-table-and-membership"
        classified_functions.append({"rva": hex(start), "end": hex(end),
                                     "pool_references": list(references.values()), "category": category})
        for rva in sites:
            if rva not in boundaries:
                raise ValueError(f"Mask instruction boundary mismatch at {rva:#x}")
            position = boundaries[rva]
            instruction = instructions[position]
            if (instruction.mnemonic != "movabs" or instruction.size != 10
                    or len(instruction.operands) != 2
                    or instruction.operands[1].type != capstone.x86.X86_OP_IMM
                    or instruction.operands[1].imm & ((1 << 64) - 1) != OLD_MASK):
                raise ValueError(f"Unexpected scalar-mask encoding at {rva:#x}")
            change(rva + 2, old_bytes, struct.pack("<Q", NEW_MASK), "pool-base-mask",
                   instruction_rva=hex(rva), function_rva=hex(start), category=category,
                   instruction_context=[{"rva": hex(item.address), "instruction": f"{item.mnemonic} {item.op_str}"}
                                        for item in instructions[position:position + 4]])

    change(0x1421575, struct.pack("<Q", 16 << 30), struct.pack("<Q", 4 << 30),
           "pool-size-and-alignment", instruction_rva="0x1421573")
    for rva in (0x74F6F24, 0x74F80F3, 0x74F9A1E):
        instruction = next(decoder.disasm(pe.get_data(rva, 6), rva))
        if instruction.mnemonic != "and" or instruction.size != 6:
            raise ValueError(f"Unexpected PCScan index instruction at {rva:#x}")
        change(rva + 2, struct.pack("<I", 0x1FFFFF), struct.pack("<I", 0x7FFFF),
               "pcscan-card-index", instruction_rva=hex(rva))
    change(0xC0807C0, old_bytes, struct.pack("<Q", NEW_MASK), "avx2-pool-mask",
           reference_instruction_rva="0x74f9cda")
    change(0xC0807C8, bytes.fromhex("00fc00fc"), bytes.fromhex("00ff00ff"),
           "sse41-sign-extended-pool-mask", reference_instruction_rva="0x74f9e8a")
    if len(edits) != 31715:
        raise ValueError(f"Expected 31715 edits, found {len(edits)}")
    binary, header_edits = common.finalize_pe(source, pe, patched, edits)
    remaining = []
    for section in pe.sections:
        if not section.Characteristics & 0x20000000:
            continue
        data = binary[section.PointerToRawData:section.PointerToRawData + section.SizeOfRawData]
        offset = data.find(old_bytes)
        while offset >= 0:
            remaining.append(section.VirtualAddress + offset - 2)
            offset = data.find(old_bytes, offset + 1)
    if set(remaining) != set(EXCLUDED):
        raise ValueError("Unexpected old masks remain in executable sections")
    manifest = {
        "source_sha256": SOURCE_SHA256, "output_sha256": common.digest(binary),
        "source_size": len(source), "output_size": len(binary), "experimental": True,
        "pool_bytes": 4 << 30, "windows_execution_verified": False,
        "metadata_layout": "Original Pool and reservation-offset-table layouts retained",
        "pcscan_card_bytes": 8192, "pcscan_physical_table_bytes": 2 << 20,
        "pcscan_reachable_table_bytes": 1 << 19,
        "scalar_mask_categories": dict(Counter(item["category"] for item in edits if item["reason"] == "pool-base-mask")),
        "excluded_scalar_masks": [{"instruction_rva": hex(rva), "reason": reason} for rva, reason in EXCLUDED.items()],
        "classified_functions": classified_functions,
        "classification_scope": "Full containing-function pool references and decoded instruction boundaries, without all-path proof",
        "edits": sorted(edits, key=lambda item: item["offset"]), "pe_header_edits": header_edits,
        "limitations": ["Complete DLL loading, Windows OS reservations, complete PCScan and Steam execution remain unverified",
                        "Physical metadata and 8 KiB cards retain the original binary geometry",
                        "The experimental binary has no Valve Authenticode signature"],
    }
    return binary, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    output = args.output_directory / "libcef.dll"
    manifest_path = args.output_directory / "libcef-patch-manifest.json"
    for target in (output, manifest_path):
        if target.resolve() == args.source.resolve() or target.exists():
            raise ValueError(f"Output must be a new file: {target}")
    binary, manifest = create_experiment(args.source.read_bytes())
    args.output_directory.mkdir(parents=True, exist_ok=True)
    output.write_bytes(binary)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output.resolve()), "sha256": manifest["output_sha256"],
                      "edits": len(manifest["edits"]), "categories": manifest["scalar_mask_categories"]}, indent=2))


if __name__ == "__main__":
    main()
