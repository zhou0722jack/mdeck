#!/usr/bin/env python3
"""Produce the pinned chrome_elf.dll 4 GiB experimental copy and edit manifest.

Requires pefile and capstone. This preserves the original metadata layouts and
8 KiB PCScan cards. It is an experimental binary, requiring execution testing.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

import capstone
import pefile


SOURCE_SHA256 = "d336f4944bb2442cbe0b66435d77f16e96c5f7c34894d5da8d89248048414fc3"
OLD_MASK = 0xFFFFFFFC00000000
NEW_MASK = 0xFFFFFFFF00000000
POOL_SLOTS = {0x13AE80: "regular", 0x13AE88: "brp"}
LEAF_RANGE = (0xE3780, 0xE37D8)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def finalize_pe(source, pe, patched, edits):
    """Remove the obsolete certificate and validate every remaining byte edit."""
    security = pe.OPTIONAL_HEADER.DATA_DIRECTORY[4]
    certificate_start = security.VirtualAddress
    certificate_size = security.Size
    if certificate_start + certificate_size != len(source):
        raise ValueError("Expected the original Authenticode certificate at EOF")
    security_offset = security.get_file_offset()
    checksum_offset = pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum")
    patched[security_offset:security_offset + 8] = b"\0" * 8
    patched[checksum_offset:checksum_offset + 4] = b"\0" * 4
    del patched[certificate_start:]
    checksum = pefile.PE(data=bytes(patched), fast_load=True).generate_checksum()
    patched[checksum_offset:checksum_offset + 4] = struct.pack("<I", checksum)
    permitted = {byte for item in edits for byte in range(
        item["offset"], item["offset"] + len(bytes.fromhex(item["before"])))}
    permitted.update(range(security_offset, security_offset + 8))
    permitted.update(range(checksum_offset, checksum_offset + 4))
    unexpected = [offset for offset, value in enumerate(patched)
                  if value != source[offset] and offset not in permitted]
    if unexpected:
        raise ValueError(f"Unlisted binary differences at {unexpected[:5]}")
    return bytes(patched), {
        "security_directory_file_offset": security_offset,
        "checksum_file_offset": checksum_offset, "checksum": checksum,
        "certificate_removed_offset": certificate_start,
        "certificate_removed_bytes": certificate_size,
        "certificate_removed_sha256": digest(source[certificate_start:]),
    }


def create_experiment(source):
    if digest(source) != SOURCE_SHA256:
        raise ValueError("Source SHA-256 differs from the pinned Valve chrome_elf.dll")
    pe = pefile.PE(data=source, fast_load=True)
    pe.parse_data_directories(directories=[1, 3])
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    functions = [(item.struct.BeginAddress, item.struct.EndAddress)
                 for item in pe.DIRECTORY_ENTRY_EXCEPTION] + [LEAF_RANGE]
    decoded_functions = {
        start: list(decoder.disasm(pe.get_data(start, end - start), start))
        for start, end in functions
    }
    boundaries = {
        instruction.address: (start, instruction)
        for start, instructions in decoded_functions.items() for instruction in instructions
    }
    edits = []
    patched = bytearray(source)

    def change(rva, before, after, reason, **evidence):
        offset = pe.get_offset_from_rva(rva)
        if len(before) != len(after) or source[offset:offset + len(before)] != before:
            raise ValueError(f"Unexpected bytes at RVA {rva:#x}")
        if any(offset < item["offset"] + len(bytes.fromhex(item["before"]))
               and item["offset"] < offset + len(before) for item in edits):
            raise ValueError(f"Overlapping edit at RVA {rva:#x}")
        patched[offset:offset + len(after)] = after
        edits.append({"rva": hex(rva), "offset": offset, "before": before.hex(),
                      "after": after.hex(), "reason": reason, **evidence})

    mask_sites = []
    for section in pe.sections:
        if not section.Characteristics & 0x20000000:
            continue
        data = section.get_data()
        needle = struct.pack("<Q", OLD_MASK)
        offset = data.find(needle)
        while offset >= 0:
            rva = section.VirtualAddress + offset - 2
            if rva not in boundaries:
                raise ValueError(f"Unclassified mask boundary at {rva:#x}")
            start, instruction = boundaries[rva]
            if instruction.mnemonic != "movabs" or instruction.size != 10:
                raise ValueError(f"Unexpected mask instruction at {rva:#x}")
            references = set()
            reference_instructions = []
            for item in decoded_functions[start]:
                for operand in item.operands:
                    if operand.type == capstone.x86.X86_OP_MEM and operand.mem.base == capstone.x86.X86_REG_RIP:
                        target = item.address + item.size + operand.mem.disp
                        if target in POOL_SLOTS:
                            references.add(POOL_SLOTS[target])
                            reference_instructions.append({
                                "rva": hex(item.address), "pool": POOL_SLOTS[target],
                                "instruction": f"{item.mnemonic} {item.op_str}"})
            if not references:
                raise ValueError(f"Mask function has no classified pool reference at {rva:#x}")
            category = "+".join(sorted(references))
            if start == LEAF_RANGE[0]:
                category = "pcscan-card-table-and-membership"
            position = next(index for index, item in enumerate(decoded_functions[start])
                            if item.address == rva)
            following = decoded_functions[start][position:position + 9]
            change(rva + 2, needle, struct.pack("<Q", NEW_MASK), "pool-base-mask",
                   instruction_rva=hex(rva), function_rva=hex(start),
                   category=category,
                   classification_scope="Mask instruction in a function referencing these pool slots",
                   pool_references=reference_instructions,
                   instruction_context=[{"rva": hex(item.address),
                                         "instruction": f"{item.mnemonic} {item.op_str}"}
                                        for item in following])
            mask_sites.append(rva)
            offset = data.find(needle, offset + 1)
    if len(mask_sites) != 99:
        raise ValueError(f"Expected 99 scalar mask instructions, found {len(mask_sites)}")

    if boundaries[0x41803][1].bytes != bytes.fromhex("48be0000000004000000"):
        raise ValueError("Unexpected pool-size initializer")
    change(0x41805, struct.pack("<Q", 16 << 30), struct.pack("<Q", 4 << 30),
           "pool-size-and-alignment", instruction_rva="0x41803")

    # Retain the old 8 KiB card granularity and the physical 2 MiB table.
    # Only the low 32 address bits participate in a 4 GiB pool's card index.
    card_sites = [0xE3794, 0xE49B3, 0xE59DE]
    for rva in card_sites:
        instruction = boundaries[rva][1]
        if instruction.mnemonic != "and" or instruction.size != 6:
            raise ValueError(f"Unexpected card-index instruction at {rva:#x}")
        change(rva + 2, struct.pack("<I", 0x1FFFFF), struct.pack("<I", 0x7FFFF),
               "pcscan-card-index", instruction_rva=hex(rva))

    change(0x10F358, struct.pack("<Q", OLD_MASK), struct.pack("<Q", NEW_MASK),
           "avx2-pool-mask", reference_instruction_rva="0xe5cfa")
    change(0x10F360, bytes.fromhex("00fc00fc"), bytes.fromhex("00ff00ff"),
           "sse41-sign-extended-pool-mask", reference_instruction_rva="0xe5eaa")

    patched, header_edits = finalize_pe(source, pe, patched, edits)
    for section in pe.sections:
        if section.Characteristics & 0x20000000:
            start = section.PointerToRawData
            if struct.pack("<Q", OLD_MASK) in patched[start:start + section.SizeOfRawData]:
                raise ValueError("An old scalar pool mask remains in executable data")

    manifest = {
        "source_sha256": SOURCE_SHA256, "output_sha256": digest(patched),
        "source_size": len(source), "output_size": len(patched),
        "experimental": True, "windows_execution_verified": False,
        "artifact_scope": "individual chrome_elf component", "pool_bytes": 4 << 30,
        "metadata_layout": "Preserved original Pool and reservation-offset-table layouts",
        "pcscan_card_bytes": 8192, "pcscan_physical_table_bytes": 2 << 20,
        "pcscan_reachable_table_bytes": 1 << 19,
        "scalar_mask_categories": dict(Counter(
            item["category"] for item in edits if item["reason"] == "pool-base-mask")),
        "edits": sorted(edits, key=lambda item: item["offset"]),
        "pe_header_edits": header_edits,
        "limitations": [
            "Function references classify scalar masks without proving every function path",
            "OS reservation, complete DLL initialization and Steam remain unverified",
            "Experimental copy has no original Valve Authenticode signature",
            "Use with the matching patched libcef.dll for a paired experiment",
        ],
    }
    return bytes(patched), manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    binary, manifest = create_experiment(args.source.read_bytes())
    args.output_directory.mkdir(parents=True, exist_ok=True)
    output = args.output_directory / "chrome_elf.dll"
    if output.resolve() == args.source.resolve():
        raise ValueError("Output must differ from the source DLL")
    manifest_path = args.output_directory / "patch-manifest.json"
    for target in (output, manifest_path):
        if target.exists():
            raise ValueError(f"Output already exists: {target}")
    output.write_bytes(binary)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output.resolve()), "sha256": manifest["output_sha256"],
                      "edits": len(manifest["edits"]),
                      "scalar_mask_categories": manifest["scalar_mask_categories"]}, indent=2))


if __name__ == "__main__":
    main()
