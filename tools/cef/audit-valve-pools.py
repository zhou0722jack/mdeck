#!/usr/bin/env python3
"""Read-only PartitionAlloc audit for the pinned Valve Windows x64 DLL pair.

Requires pefile and capstone. Produces JSON on stdout. Addresses are RVAs.
The instruction inventory is deliberately bounded to specified encodings.
It is not a complete patch list or a proof of runtime behavior.
"""

import argparse
import bisect
import hashlib
import json
import struct
from collections import defaultdict
from pathlib import Path

import capstone
import pefile


SPECS = {
    "libcef.dll": {
        "sha256": "6a634357cc37083902216adea2dfc65208e03ac06c07835477eeb130c8f887c2",
        "regular_base": 0xC9766C0,
        "brp_base": 0xC9766C8,
        "ranges": {
            "pool_initialization": (0x1421560, 0x1421659),
            "alloc_pages_wrapper": (0x1904990, 0x19049BF),
            "alloc_pages_with_align_offset": (0x19049C0, 0x1904D8F),
            "virtual_alloc_retry": (0x19045F0, 0x19048E4),
            "pool_get_instance": (0x1917A30, 0x1917A40),
            "pool_add": (0x1917A40, 0x1917AE2),
            "reserve_first_superpage": (0x1917AF0, 0x1917B3D),
            "membership_example": (0x2673A0, 0x267460),
            "offset_table_lookup_example": (0x352A830, 0x352A877),
        },
    },
    "chrome_elf.dll": {
        "sha256": "d336f4944bb2442cbe0b66435d77f16e96c5f7c34894d5da8d89248048414fc3",
        "regular_base": 0x13AE80,
        "brp_base": 0x13AE88,
        "ranges": {
            "pool_initialization": (0x417F0, 0x418E9),
            "alloc_pages_wrapper": (0x47BC0, 0x47BEF),
            "alloc_pages_with_align_offset": (0x47BF0, 0x47FBF),
            "virtual_alloc_retry": (0x47820, 0x47B14),
            "pool_get_instance": (0x47FF0, 0x48000),
            "pool_add": (0x48000, 0x480A2),
            "reserve_first_superpage": (0x480B0, 0x480FD),
            "membership_example": (0x48690, 0x486E5),
            "offset_table_lookup_example": (0x67F80, 0x67FC7),
        },
    },
}


def positions(data, needle):
    start = data.find(needle)
    while start >= 0:
        yield start
        start = data.find(needle, start + 1)


def instruction_record(instruction, imports):
    result = {
        "rva": hex(instruction.address), "bytes": instruction.bytes.hex(),
        "instruction": f"{instruction.mnemonic} {instruction.op_str}".strip(),
    }
    for operand in instruction.operands:
        if operand.type == capstone.x86.X86_OP_MEM and operand.mem.base == capstone.x86.X86_REG_RIP:
            target = instruction.address + instruction.size + operand.mem.disp
            result["rip_target_rva"] = hex(target)
            if target in imports:
                result["import"] = imports[target]
        if instruction.mnemonic in ("call", "jmp") and operand.type == capstone.x86.X86_OP_IMM:
            result["direct_target_rva"] = hex(operand.imm)
    return result


def immediate_inventory(pe, spec, decoder, value):
    functions = sorted(
        (entry.struct.BeginAddress, entry.struct.EndAddress)
        for entry in pe.DIRECTORY_ENTRY_EXCEPTION
    )
    starts = [start for start, _ in functions]
    groups = defaultdict(list)
    uncovered = []
    needle = struct.pack("<Q", value)
    raw_hits = 0
    movabs_hits = 0
    for section in pe.sections:
        if not section.Characteristics & 0x20000000:
            continue
        data = section.get_data()
        for offset in positions(data, needle):
            raw_hits += 1
            start = offset - 2
            if start < 0 or data[start] not in (0x48, 0x49) or not 0xB8 <= data[start + 1] <= 0xBF:
                continue
            movabs_hits += 1
            rva = section.VirtualAddress + start
            index = bisect.bisect_right(starts, rva) - 1
            if index >= 0 and rva + 10 <= functions[index][1]:
                groups[functions[index]].append(rva)
            else:
                uncovered.append(hex(rva))
    verified = []
    rejected = []
    for (start, end), candidates in groups.items():
        boundaries = {
            address for address, _, _, _ in decoder.disasm_lite(pe.get_data(start, end - start), start)
        }
        for rva in candidates:
            if rva not in boundaries:
                rejected.append(hex(rva))
                continue
            following = list(decoder.disasm(pe.get_data(rva, 96), rva))
            base_references = sorted({
                instruction.address + instruction.size + operand.mem.disp
                for instruction in following for operand in instruction.operands
                if operand.type == capstone.x86.X86_OP_MEM
                and operand.mem.base == capstone.x86.X86_REG_RIP
                and instruction.address + instruction.size + operand.mem.disp
                in (spec["regular_base"], spec["brp_base"])
            })
            verified.append({
                "rva": hex(rva), "file_offset": hex(pe.get_offset_from_rva(rva)),
                "function_rva": hex(start),
                "instruction": following[0].mnemonic + " " + following[0].op_str,
                "nearby_pool_base_references": [hex(value) for value in base_references],
            })
    return {
        "encoding": f"movabs r64, {value:#x}",
        "raw_eight_byte_matches": raw_hits,
        "matching_ten_byte_encodings": movabs_hits,
        "verified_on_unwind_function_instruction_boundaries": len(verified),
        "with_pool_base_reference_in_following_96_bytes": sum(
            bool(item["nearby_pool_base_references"]) for item in verified
        ),
        "unwind_uncovered_candidate_rvas": uncovered,
        "rejected_boundary_candidate_rvas": rejected,
        "instructions": verified,
        "scope": "One immediate encoding. Nearby references do not prove data flow. Other encodings and constants remain unaudited.",
    }


def audit(path, spec):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != spec["sha256"]:
        raise ValueError(f"Unexpected {path.name} SHA-256: {digest}")
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories(directories=[1, 3])
    if pe.FILE_HEADER.Machine != 0x8664:
        raise ValueError("Windows x64 PE required")
    imports = {
        symbol.address - pe.OPTIONAL_HEADER.ImageBase:
        library.dll.decode() + "!" + symbol.name.decode()
        for library in pe.DIRECTORY_ENTRY_IMPORT for symbol in library.imports if symbol.name
    }
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    ranges = {
        name: {
            "start_rva": hex(start), "end_rva": hex(end),
            "instructions": [
                instruction_record(instruction, imports)
                for instruction in decoder.disasm(pe.get_data(start, end - start), start)
            ],
        }
        for name, (start, end) in spec["ranges"].items()
    }
    initialization = ranges["pool_initialization"]["instructions"]
    referenced_slots = {item.get("rip_target_rva") for item in initialization}
    if not {hex(spec["regular_base"]), hex(spec["brp_base"])} <= referenced_slots:
        raise ValueError(f"Pool base slots do not match {path.name} initializer")
    if sum(item["instruction"] == "movabs rsi, 0x400000000" for item in initialization) != 1:
        raise ValueError(f"Unexpected initial pool size in {path.name}")
    pool_add = {item["instruction"] for item in ranges["pool_add"]["instructions"]}
    if not {"shr r9, 0x15", "mov qword ptr [rsi + 0x410], r9", "cmp r9, 0x2001"} <= pool_add:
        raise ValueError(f"Unexpected dynamic pool capacity in {path.name}")
    constants = [0x400000000, 0x3FFFFFFFF, 0xFFFFFFFC00000000,
                 0x200000000, 0xFFFFFFFF00000000]
    constant_counts = {hex(value): 0 for value in constants}
    for section in pe.sections:
        if section.Characteristics & 0x20000000:
            data = section.get_data()
            for value in constants:
                constant_counts[hex(value)] += data.count(struct.pack("<Q", value))
    return {
        "path": str(path.resolve()), "sha256": digest,
        "image_base": hex(pe.OPTIONAL_HEADER.ImageBase),
        "regular_pool_base_slot_rva": hex(spec["regular_base"]),
        "brp_pool_base_slot_rva": hex(spec["brp_base"]),
        "ranges": ranges,
        "mask_inventory": immediate_inventory(pe, spec, decoder, 0xFFFFFFFC00000000),
        "size_inventory": immediate_inventory(pe, spec, decoder, 0x400000000),
        "offset_mask_inventory": immediate_inventory(pe, spec, decoder, 0x3FFFFFFFF),
        "raw_eight_byte_constant_counts_in_executable_sections": constant_counts,
        "constant_count_scope": "Byte matches, without instruction or semantic classification.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dll_directory", type=Path)
    args = parser.parse_args()
    report = {
        "execution_performed": False, "binaries_modified": False,
        "patch_completeness_established": False,
        "dlls": {name: audit(args.dll_directory / name, spec) for name, spec in SPECS.items()},
    }
    base = 0x1000000000
    address = base + 0x100000000
    report["boundary_counterexample"] = {
        "pool_base": hex(base), "four_gib_pool_end": hex(address),
        "old_16_gib_mask_classifies_end_as_inside": address & 0xFFFFFFFC00000000 == base,
        "new_4_gib_mask_classifies_end_as_inside": address & 0xFFFFFFFF00000000 == base,
        "scope": "Integer arithmetic example. No DLL execution.",
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
