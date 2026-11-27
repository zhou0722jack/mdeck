#!/usr/bin/env python3
"""Execute pinned DLL allocator instructions with explicitly mocked OS services.

Requires pefile, capstone and unicorn. Native SIMD checks use the companion
x86_64 macOS harness. These are component tests, without a Windows DLL loader.
"""

import argparse
import gc
import importlib.util
import json
from pathlib import Path
import random
import resource
import struct
import subprocess
import tempfile

import capstone
import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE
import unicorn.x86_const as x86


ROOT = Path(__file__).resolve().parents[2]
BASE = 0x180000000
STACK = 0x30000000
SCRATCH = 0x31000000
STUBS = 0x32000000
STOP = STUBS + 0xF000
PAGE = 2 << 20

ELF = {
    "init": 0x417F0, "regular_allocate": 0x47BC0, "aligned_allocate": 0x47BF0,
    "decommit": 0x47FC0, "random_hint": 0x4C2C0, "memset": 0xB4170,
    "manager": 0x47FF0, "reserve": 0x480B0, "try_reserve": 0x48220,
    "unreserve": 0x48300, "regular_slot": 0x13AE80, "brp_slot": 0x13AE88,
    "card_leaf": 0xE3780, "card_fragments": ((0xE3790, 0xE379A, x86.UC_X86_REG_RDX),
        (0xE49AF, 0xE49B9, x86.UC_X86_REG_RDX), (0xE59DA, 0xE59E4, x86.UC_X86_REG_RSI)),
    "offset_table": 0x13AF84, "offset_fragment": (0x67F89, 0x67FA7),
    "scanner": 0xE4030, "avx": (0xE5CD0, 0xE5E6F), "mark": 0xE5F70,
}
LIBCEF = {
    "init": 0x1421560, "regular_allocate": 0x1904990, "aligned_allocate": 0x19049C0,
    "decommit": 0x1904E20, "random_hint": 0x1EEF2E0, "memset": 0x3BA9760,
    "manager": 0x1917A30, "reserve": 0x1917AF0, "try_reserve": 0x1917C60,
    "unreserve": 0x1917D40, "regular_slot": 0xC9766C0, "brp_slot": 0xC9766C8,
    "card_leaf": 0x74F6F10, "card_fragments": ((0x74F6F20, 0x74F6F2A, x86.UC_X86_REG_RDX),
        (0x74F80EF, 0x74F80F9, x86.UC_X86_REG_RDX), (0x74F9A1A, 0x74F9A24, x86.UC_X86_REG_RSI)),
    "offset_table": 0xC96A6A4, "offset_fragment": (0x352A830, 0x352A84E),
    "scanner": 0x74F7790, "avx": (0x74F9CB0, 0x74F9E4F), "mark": 0x74F9F50,
}


class Machine:
    def __init__(self, binary, layout=ELF):
        # Hooks retain this object. Collect finished machines before loading a
        # large libcef image for the next independent component test.
        gc.collect()
        self.layout = layout
        self.pe = pefile.PE(data=binary, fast_load=True)
        self.pe.parse_data_directories(directories=[1])
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.uc.mem_map(BASE, (self.pe.OPTIONAL_HEADER.SizeOfImage + 4095) & -4096)
        self.uc.mem_write(BASE, self.pe.get_memory_mapped_image())
        for address in (STACK, SCRATCH, STUBS):
            self.uc.mem_map(address, 0x10000)
        self.hooks = {}
        self.calls = []
        self.regular = 0x1000000000
        self.brp = 0x1800000000
        self.mock_allocations = True
        self.fail_reservations = False
        self.reservation_failures_remaining = 0
        self.reservation_attempts = 0
        for library in self.pe.DIRECTORY_ENTRY_IMPORT:
            for symbol in library.imports:
                if not symbol.name:
                    continue
                address = STUBS + len(self.hooks) * 16
                self.hooks[address] = symbol.name.decode()
                self.uc.mem_write(symbol.address, struct.pack("<Q", address))
        self.uc.hook_add(UC_HOOK_CODE, self.import_hook, begin=STUBS, end=STUBS + 0xEFFF)
        for rva in (layout[key] for key in ("regular_allocate", "aligned_allocate", "decommit", "random_hint", "memset")):
            self.uc.hook_add(UC_HOOK_CODE, self.direct_hook, begin=BASE + rva, end=BASE + rva)

    def read64(self, address):
        return struct.unpack("<Q", self.uc.mem_read(address, 8))[0]

    def write64(self, address, value):
        self.uc.mem_write(address, struct.pack("<Q", value))

    def args(self):
        return [self.uc.reg_read(register) for register in
                (x86.UC_X86_REG_RCX, x86.UC_X86_REG_RDX,
                 x86.UC_X86_REG_R8, x86.UC_X86_REG_R9)]

    def finish(self, value=0):
        stack = self.uc.reg_read(x86.UC_X86_REG_RSP)
        self.uc.reg_write(x86.UC_X86_REG_RAX, value)
        self.uc.reg_write(x86.UC_X86_REG_RIP, self.read64(stack))
        self.uc.reg_write(x86.UC_X86_REG_RSP, stack + 8)

    def import_hook(self, uc, address, size, context):
        name = self.hooks[address]
        args = self.args()
        if name in ("TryAcquireSRWLockExclusive", "ReleaseSRWLockExclusive"):
            self.finish(1)
        elif name == "VirtualAlloc":
            self.calls.append({"function": name, "args": args})
            self.reservation_attempts += 1
            failed = self.fail_reservations or self.reservation_failures_remaining > 0
            self.reservation_failures_remaining = max(0, self.reservation_failures_remaining - 1)
            self.finish(0 if failed else args[0] or 0x2600010000)
        elif name == "GetLastError":
            self.finish(487)
        elif name == "VirtualFree":
            self.calls.append({"function": name, "args": args})
            self.finish(1)
        else:
            raise AssertionError(f"Unexpected OS/CRT service {name} at {address:#x}")

    def direct_hook(self, uc, address, size, context):
        rva = address - BASE
        args = self.args()
        if rva in (self.layout["regular_allocate"], self.layout["aligned_allocate"]) and self.mock_allocations:
            self.calls.append({"function": hex(rva), "args": args})
            self.finish(self.regular if rva == self.layout["regular_allocate"] else self.brp - 0x10000)
        elif rva == self.layout["decommit"]:
            self.calls.append({"function": "decommit", "args": args})
            self.finish()
        elif rva == self.layout["random_hint"]:
            self.finish(0x2500000000)
        elif rva == self.layout["memset"]:
            uc.mem_write(args[0], bytes([args[1] & 255]) * args[2])
            self.finish(args[0])

    def call(self, rva, *args, count=2000000):
        stack = STACK + 0xFEF8
        self.uc.reg_write(x86.UC_X86_REG_RSP, stack)
        self.uc.mem_write(stack, struct.pack("<Q", STOP) + bytes(0x78))
        for register, value in zip((x86.UC_X86_REG_RCX, x86.UC_X86_REG_RDX,
                                    x86.UC_X86_REG_R8, x86.UC_X86_REG_R9), args):
            self.uc.reg_write(register, value)
        for index, value in enumerate(args[4:]):
            self.write64(stack + 0x28 + index * 8, value)
        self.uc.emu_start(BASE + rva, STOP, count=count)
        if self.uc.reg_read(x86.UC_X86_REG_RIP) != STOP:
            raise AssertionError(f"Instruction budget exhausted at RVA {rva:#x}")
        return self.uc.reg_read(x86.UC_X86_REG_RAX)

    def fragment(self, start, end, registers):
        for register, value in registers.items():
            self.uc.reg_write(register, value)
        self.uc.emu_start(BASE + start, BASE + end, count=100)
        assert self.uc.reg_read(x86.UC_X86_REG_RIP) == BASE + end


def allocator_test(binary, pool_bytes, layout=ELF):
    machine = Machine(binary, layout)
    machine.call(layout["init"])
    initialization_calls = [item for item in machine.calls if item["function"] in
                            (hex(layout["regular_allocate"]), hex(layout["aligned_allocate"]))]
    assert initialization_calls[0]["args"][:2] == [pool_bytes, pool_bytes]
    assert initialization_calls[1]["args"] == [0, pool_bytes + 0x10000, pool_bytes, pool_bytes - 0x10000]
    manager = machine.call(layout["manager"])
    capacity = pool_bytes // PAGE
    for handle, base in ((1, machine.regular), (2, machine.brp)):
        pool = manager + (handle - 1) * 0x420
        assert machine.read64(pool + 0x410) == capacity
        assert machine.read64(pool + 0x418) == base
    # Initialization has already reserved the regular pool's first superpage.
    assert machine.call(layout["reserve"], manager, 1, 0, pool_bytes - PAGE) == machine.regular + PAGE
    assert machine.call(layout["reserve"], manager, 1, 0, PAGE) == 0
    assert machine.call(layout["try_reserve"], manager, machine.regular + pool_bytes, PAGE) == 0
    machine.call(layout["unreserve"], manager, 1, machine.regular + pool_bytes - PAGE, PAGE)
    assert machine.call(layout["reserve"], manager, 1, 0, PAGE) == machine.regular + pool_bytes - PAGE
    machine.call(layout["unreserve"], manager, 1, machine.regular, pool_bytes)
    assert machine.call(layout["reserve"], manager, 1, 0, pool_bytes) == machine.regular
    assert machine.call(layout["reserve"], manager, 1, 0, PAGE) == 0
    assert machine.call(layout["reserve"], manager, 2, 0, pool_bytes) == machine.brp
    machine.call(layout["unreserve"], manager, 1, machine.regular, pool_bytes)
    requested = machine.regular + 7 * PAGE
    assert machine.call(layout["reserve"], manager, 1, requested, PAGE) == requested
    machine.call(layout["unreserve"], manager, 1, requested, PAGE)
    used = [False] * capacity
    allocations = []
    randomizer = random.Random(126)
    for step in range(1200):
        if allocations and randomizer.randrange(3) == 0:
            index = randomizer.randrange(len(allocations))
            first, pages = allocations.pop(index)
            machine.call(layout["unreserve"], manager, 1, machine.regular + first * PAGE, pages * PAGE)
            used[first:first + pages] = [False] * pages
        else:
            pages = randomizer.randrange(1, 65)
            candidates = [first for first in range(capacity - pages + 1)
                          if not any(used[first:first + pages])]
            result = machine.call(layout["reserve"], manager, 1, 0, pages * PAGE)
            assert bool(result) == bool(candidates)
            if result:
                first = (result - machine.regular) // PAGE
                assert first == candidates[0]
                used[first:first + pages] = [True] * pages
                allocations.append((first, pages))
        actual = machine.uc.mem_read(manager + 8, 1024)
        assert all(bool(actual[index // 8] & (1 << (index % 8))) == used[index]
                   for index in range(capacity))
        assert not any(actual[(capacity + 7) // 8:])
    return {"pool_bytes": pool_bytes, "capacity_pages": capacity,
            "random_operations": 1200, "exhaustion_reuse_requested_address": "passed",
            "initialization_call_arguments": initialization_calls}


def reservations_test(binary, pool_bytes, layout=ELF):
    machine = Machine(binary, layout)
    machine.mock_allocations = False
    machine.call(layout["regular_allocate"], pool_bytes, pool_bytes, 0, 253, 0xFFFFFFFF)
    regular = next(item for item in machine.calls if item["function"] == "VirtualAlloc")
    assert regular["args"][1:] == [pool_bytes, 0x2000, 1]
    machine.calls.clear()
    machine.call(layout["aligned_allocate"], 0, pool_bytes + 0x10000, pool_bytes, pool_bytes - 0x10000, 0, 253, 0xFFFFFFFF)
    brp = next(item for item in machine.calls if item["function"] == "VirtualAlloc")
    assert brp["args"][1:] == [pool_bytes + 0x10000, 0x2000, 1]
    assert brp["args"][0] % pool_bytes == pool_bytes - 0x10000
    fallbacks = []
    for brp_pool in (False, True):
        fallback = Machine(binary, layout)
        fallback.mock_allocations = False
        fallback.reservation_failures_remaining = 3
        length = pool_bytes + (0x10000 if brp_pool else 0)
        alignment_offset = pool_bytes - 0x10000 if brp_pool else 0
        address = fallback.call(layout["aligned_allocate"], 0, length, pool_bytes, alignment_offset, 0, 253, 0xFFFFFFFF)
        allocations = [item for item in fallback.calls if item["function"] == "VirtualAlloc"]
        releases = [item for item in fallback.calls if item["function"] == "VirtualFree"]
        assert len(allocations) == 5 and len(releases) == 1
        assert allocations[3]["args"] == [0, length + pool_bytes - 0x10000, 0x2000, 1]
        assert allocations[4]["args"] == [address, length, 0x2000, 1]
        assert address % pool_bytes == alignment_offset
        fallbacks.append({"brp": brp_pool, "oversized_temporary_reservation_bytes": allocations[3]["args"][1],
                          "final_reservation_bytes": length, "retry_and_release": "passed"})
    return {"regular_virtual_alloc": regular, "brp_virtual_alloc": brp,
            "fallback_paths": fallbacks,
            "os_services": "mocked, with real DLL allocation and retry instructions"}


def cards_and_offsets_test(binary, pool_bytes, layout=ELF):
    machine = Machine(binary, layout)
    checks = 0
    for placement in range(4):
        base = 0x1000000000 + placement * pool_bytes
        machine.write64(BASE + layout["regular_slot"], base)
        machine.write64(BASE + layout["brp_slot"], base + 8 * pool_bytes)
        machine.uc.mem_map(base, 2 << 20)
        for offset in (0, 1, 8191, 8192, PAGE, pool_bytes - PAGE, pool_bytes - 1):
            address = base + offset
            expected = offset >> 13
            for start, end, register in layout["card_fragments"]:
                machine.fragment(start, end, {register: address})
                assert machine.uc.reg_read(register) == expected
                checks += 1
            machine.uc.mem_write(base + expected, b"\1")
            assert machine.call(layout["card_leaf"], 0, address) == (address & -PAGE) | 0x4000
            machine.uc.mem_write(base + expected, b"\0")
            assert machine.call(layout["card_leaf"], 0, address) == 0
        machine.uc.mem_unmap(base, 2 << 20)
    brp = machine.brp
    machine.write64(BASE + layout["brp_slot"], brp)
    for index in (0, 1, 511, 1023, 2047):
        tag = 0xA000 + index
        machine.uc.mem_write(BASE + layout["offset_table"] + 0x4000 + index * 2, struct.pack("<H", tag))
        machine.fragment(*layout["offset_fragment"], {x86.UC_X86_REG_RCX: brp + index * PAGE})
        assert machine.uc.reg_read(x86.UC_X86_REG_R10) == tag
    return {"card_index_checks": checks, "card_read_mark_clear": "passed",
            "preserved_offset_table_stride": "passed",
            "card_granularity_bytes": 8192}


def emulated_avx_test(binary, pool_bytes, layout=ELF):
    """Run the real scanner's control flow with explicit VEX instruction semantics.

    Unicorn 2.1.4 cannot execute these AVX instructions. The small interpreter
    below handles only the listed vector operations. Every other instruction
    runs in Unicorn, and an unexpected vector operation fails the test.
    """
    machine = Machine(binary, layout)
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    start, end = layout["avx"]
    instructions = list(decoder.disasm(machine.pe.get_data(start, end - start), BASE + start))
    vector_instructions = {item.address: item for item in instructions if item.mnemonic.startswith("v")}
    vectors = {f"ymm{index}": bytes(32) for index in range(16)}
    observed = []
    executed = set()

    def address_of(instruction, operand):
        memory = operand.mem
        address = memory.disp
        if memory.base == capstone.x86.X86_REG_RIP:
            address += instruction.address + instruction.size
        elif memory.base:
            address += machine.uc.reg_read(getattr(x86, "UC_X86_REG_" + instruction.reg_name(memory.base).upper()))
        if memory.index:
            address += memory.scale * machine.uc.reg_read(getattr(
                x86, "UC_X86_REG_" + instruction.reg_name(memory.index).upper()))
        return address

    def read(instruction, operand):
        if operand.type == capstone.x86.X86_OP_MEM:
            return bytes(machine.uc.mem_read(address_of(instruction, operand), operand.size))
        name = instruction.reg_name(operand.reg)
        if name.startswith(("ymm", "xmm")):
            return vectors[name.replace("xmm", "ymm")][:operand.size]
        value = machine.uc.reg_read(getattr(x86, "UC_X86_REG_" + name.upper()))
        return value.to_bytes(operand.size, "little")

    def write(instruction, operand, value):
        if operand.type == capstone.x86.X86_OP_MEM:
            machine.uc.mem_write(address_of(instruction, operand), value[:operand.size])
            return
        name = instruction.reg_name(operand.reg)
        if name.startswith(("ymm", "xmm")):
            vectors[name.replace("xmm", "ymm")] = value[:operand.size].ljust(32, b"\0")
        else:
            machine.uc.reg_write(getattr(x86, "UC_X86_REG_" + name.upper()), int.from_bytes(value, "little"))

    def vector_hook(uc, address, size, context):
        instruction = vector_instructions.get(address)
        if instruction is None:
            return
        operands = instruction.operands
        operation = instruction.mnemonic
        executed.add(operation)
        if operation == "vpbroadcastq":
            value = read(instruction, operands[1]) * 4
        elif operation in ("vmovdqa", "vmovdqu", "vmovq"):
            value = read(instruction, operands[1])[:operands[0].size]
        elif operation == "vpand":
            value = bytes(left & right for left, right in zip(
                read(instruction, operands[1]), read(instruction, operands[2])))
        elif operation == "vpcmpeqq":
            left, right = (read(instruction, operand) for operand in operands[1:])
            value = b"".join(b"\xff" * 8 if left[index:index + 8] == right[index:index + 8]
                             else bytes(8) for index in range(0, 32, 8))
        elif operation == "vmovmskpd":
            vector = read(instruction, operands[1])
            value = sum((vector[index * 8 + 7] >> 7) << index for index in range(4)).to_bytes(4, "little")
        elif operation == "vpextrq":
            vector = read(instruction, operands[1])
            index = operands[2].imm
            value = vector[index * 8:index * 8 + 8]
        elif operation == "vextracti128":
            vector = read(instruction, operands[1])
            index = operands[2].imm
            value = vector[index * 16:index * 16 + 16]
        elif operation == "vzeroupper":
            for name, vector in vectors.items():
                vectors[name] = vector[:16] + bytes(16)
            uc.reg_write(x86.UC_X86_REG_RIP, address + instruction.size)
            return
        else:
            raise AssertionError(f"Unexpected vector operation {operation}")
        write(instruction, operands[0], value)
        uc.reg_write(x86.UC_X86_REG_RIP, address + instruction.size)

    def mark_hook(uc, address, size, context):
        observed.append(uc.reg_read(x86.UC_X86_REG_RDX))
        machine.finish()

    machine.uc.hook_add(UC_HOOK_CODE, vector_hook, begin=BASE + start, end=BASE + end)
    machine.uc.hook_add(UC_HOOK_CODE, mark_hook, begin=BASE + layout["mark"], end=BASE + layout["mark"])
    cases = 0
    for placement in range(4):
        base = 0x1000000000 + placement * pool_bytes
        machine.write64(BASE + layout["regular_slot"], base)
        candidates = [0, base - 1, base, base + 1, base + pool_bytes - 1,
                      base + pool_bytes, base + pool_bytes + PAGE, base + pool_bytes * 2]
        for count in range(32):
            values = [candidates[index % len(candidates)] for index in range(count)]
            machine.uc.mem_write(SCRATCH, b"".join(struct.pack("<Q", value) for value in values) or bytes(8))
            observed.clear()
            machine.call(start, SCRATCH + 0x1000, SCRATCH, SCRATCH + count * 8)
            assert observed == [value for value in values if base <= value < base + pool_bytes]
            cases += 1
    return {"cases": cases, "result": "passed", "vector_operations": sorted(executed),
            "execution": "Unicorn control flow plus explicit AVX instruction semantics, mark callback mocked",
            "native_avx2_execution": False}


def pe_integrity_test(source, patched):
    original_pe = pefile.PE(data=source, fast_load=True)
    patched_pe = pefile.PE(data=patched, fast_load=True)
    assert original_pe.FILE_HEADER.Machine == patched_pe.FILE_HEADER.Machine == 0x8664
    for field in ("ImageBase", "AddressOfEntryPoint", "SizeOfImage", "DllCharacteristics"):
        assert getattr(original_pe.OPTIONAL_HEADER, field) == getattr(patched_pe.OPTIONAL_HEADER, field)
    assert [section.__pack__() for section in original_pe.sections] == [
        section.__pack__() for section in patched_pe.sections]
    checked = []
    for index, (before, after) in enumerate(zip(original_pe.OPTIONAL_HEADER.DATA_DIRECTORY,
                                               patched_pe.OPTIONAL_HEADER.DATA_DIRECTORY)):
        if index == 4:
            assert after.VirtualAddress == after.Size == 0
            continue
        assert before.VirtualAddress == after.VirtualAddress and before.Size == after.Size
        if before.Size:
            assert original_pe.get_data(before.VirtualAddress, before.Size) == patched_pe.get_data(
                after.VirtualAddress, after.Size)
            checked.append(pefile.DIRECTORY_ENTRY[index])
    patched_pe.parse_data_directories(directories=[0])
    return {"machine": "AMD64", "entry_point_and_image_geometry": "preserved",
            "unchanged_directory_bytes": checked,
            "export_count": len(patched_pe.DIRECTORY_ENTRY_EXPORT.symbols),
            "authenticode_certificate_removed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("patched", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--library", choices=("chrome-elf", "libcef"), default="chrome-elf")
    args = parser.parse_args()
    layout = LIBCEF if args.library == "libcef" else ELF
    source = args.original.read_bytes()
    patched = args.patched.read_bytes()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    tool = "patch-valve-libcef-pools.py" if args.library == "libcef" else "patch-valve-elf-pools.py"
    spec = importlib.util.spec_from_file_location("patch_dll", ROOT / "tools/cef" / tool)
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)
    reproduced, manifest = patcher.create_experiment(source)
    assert reproduced == patched
    try:
        patcher.create_experiment(source[:-1] + bytes([source[-1] ^ 1]))
    except ValueError:
        pass
    else:
        raise AssertionError("Altered input accepted")
    geometry_checks = 0
    for edit in manifest["edits"]:
        if edit["reason"] != "pool-base-mask":
            continue
        mask = struct.unpack_from("<Q", patched, edit["offset"])[0]
        for placement in range(4):
            base = 0x1000000000 + placement * (4 << 30)
            for offset in (-1, 0, 1, (4 << 30) - 1, 4 << 30, 8 << 30):
                assert ((base + offset) & mask == base) == (0 <= offset < 4 << 30)
                geometry_checks += 1
    result = {"reproducible_patch": "passed", "wrong_input_rejected": "passed",
              "scalar_mask_boundary_checks": geometry_checks,
              "patched_sha256": manifest["output_sha256"], "library": args.library, "component_execution": {},
              "windows_execution": False, "steam_execution": False}
    result["pe_integrity"] = pe_integrity_test(source, patched)
    for name, binary, pool_bytes in (("original", source, 16 << 30), ("patched", patched, 4 << 30)):
        print(f"Executing {name} allocator instructions", flush=True)
        result["component_execution"][name] = allocator_test(binary, pool_bytes, layout)
        result["component_execution"][name]["reservations"] = reservations_test(binary, pool_bytes, layout)
    # Test the 4 GiB card geometry at all four placements in an old 16 GiB window.
    result["patched_cards_and_offsets"] = cards_and_offsets_test(patched, 4 << 30, layout)
    result["avx_component_emulation"] = {
        name: emulated_avx_test(binary, pool_bytes, layout)
        for name, binary, pool_bytes in (("original", source, 16 << 30), ("patched", patched, 4 << 30))}
    restored_avx = bytearray(patched)
    avx_edit = next(edit for edit in manifest["edits"] if edit["reason"] == "avx2-pool-mask")
    restored_avx[avx_edit["offset"]:avx_edit["offset"] + 8] = bytes.fromhex(avx_edit["before"])
    try:
        emulated_avx_test(bytes(restored_avx), 4 << 30, layout)
    except AssertionError:
        result["missing_avx_patch_detected"] = "passed"
    else:
        raise AssertionError("Missing AVX mask patch escaped the scanner test")
    with tempfile.TemporaryDirectory(prefix="mdeck-cef-native-simd-") as folder:
        work = Path(folder)
        executable = work / "scanner"
        subprocess.run(["clang", "-arch", "x86_64", "-O2",
                        str(ROOT / "tests/host/cef-elf-scanner.c"), "-o", str(executable)], check=True)
        native = []
        for name, binary, pool_bytes in (("original", source, 16 << 30), ("patched", patched, 4 << 30)):
            image = work / f"{name}.image"
            image.write_bytes(pefile.PE(data=binary, fast_load=True).get_memory_mapped_image())
            native.append(subprocess.check_output([str(executable), str(image), str(pool_bytes),
                hex(layout["scanner"]), hex(layout["mark"]), hex(layout["regular_slot"])], text=True).strip())
        result["native_x86_scanners"] = native
        restored_sse = bytearray(patched)
        sse_edit = next(edit for edit in manifest["edits"] if edit["reason"] == "sse41-sign-extended-pool-mask")
        restored_sse[sse_edit["offset"]:sse_edit["offset"] + 4] = bytes.fromhex(sse_edit["before"])
        image = work / "missing-sse-patch.image"
        image.write_bytes(pefile.PE(data=bytes(restored_sse), fast_load=True).get_memory_mapped_image())
        failure = subprocess.run([str(executable), str(image), str(4 << 30),
            hex(layout["scanner"]), hex(layout["mark"]), hex(layout["regular_slot"])], capture_output=True, text=True)
        assert failure.returncode < 0 and "Assertion failed" in failure.stderr
        result["missing_sse_patch_detected"] = "passed"
    print(json.dumps(result, indent=2))
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
