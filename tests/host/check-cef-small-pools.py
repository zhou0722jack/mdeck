#!/usr/bin/env python3
"""Exercise the pinned Chromium pool algorithms without Chromium OS allocation.

This extracts production constant selectors, masks, metadata lengths, the Pool
class and its methods. Host mutexes/checks replace Chromium infrastructure.
It does not build CEF or reserve the simulated guest addresses.
"""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def braced_declaration(source, marker):
    start = source.index(marker)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def generate_fixture(source_dir):
    constants = (source_dir / "partition_alloc_constants.h").read_text()
    start = constants.index("#if PA_BUILDFLAG(HAS_64_BIT_POINTERS)",
                            constants.index("// Maximum pool size."))
    end = constants.index("\n", constants.index(
        "constexpr size_t kMaxSuperPagesInPool =", start))
    selector = constants[start:end]
    superpage_start = constants.index("constexpr size_t kSuperPageShift =")
    superpage_end = constants.index(";", superpage_start) + 1
    superpage_shift = constants[superpage_start:superpage_end]

    address = (source_dir / "partition_address_space.h").read_text()
    start = address.index("  static constexpr size_t kRegularPoolSize =")
    end = address.index("\n#if BUILDFLAG(IS_IOS)", start)
    sizes = address[start:end]
    start = address.index("  static constexpr uintptr_t kRegularPoolOffsetMask =")
    end = address.index("#endif  // !PA_CONFIG(DYNAMICALLY_SELECT_POOL_SIZE)", start)
    masks = address[start:end]

    table = (source_dir / "reservation_offset_table.h").read_text()
    start = table.index("  static constexpr size_t kReservationOffsetTableCoverage =")
    end = table.index("#else", start)
    table_sizes = table[start:end]

    header = (source_dir / "address_pool_manager.h").read_text()
    pool = braced_declaration(header, "  class Pool {") + ";"
    implementation = (source_dir / "address_pool_manager.cc").read_text()
    methods = []
    for method in ("void Initialize", "bool IsInitialized", "void Reset",
                   "void GetUsedSuperPages", "uintptr_t GetBaseAddress",
                   "uintptr_t FindChunk", "bool TryReserveChunk", "void FreeChunk"):
        result, name = method.split()
        marker = result + " AddressPoolManager::Pool::" + name + "("
        body = braced_declaration(implementation, marker)
        methods.append(body.replace("AddressPoolManager::Pool::", "Pool::", 1))

    superpage_constants = (superpage_shift + "\n"
                           "constexpr size_t kSuperPageSize = size_t{1} << kSuperPageShift;\n"
                           "constexpr size_t kSuperPageOffsetMask = kSuperPageSize - 1;\n")
    return PREFIX + superpage_constants + selector + "\nstruct Geometry {\n" + \
        sizes + masks + table_sizes + "\n};\n" + pool + "\n" + \
        "\n".join(methods) + SUFFIX


def compile_windows_components(chromium_src, work, compiler, expected_gib):
    source = chromium_src / "base/allocator/partition_allocator/src"
    generated = work / "gen"
    flags = set()
    for path in source.rglob("*.h"):
        flags.update(re.findall(r"PA_BUILDFLAG\((\w+)\)", path.read_text()))
    flags.discard("flag")
    enabled = {"HAS_64_BIT_POINTERS", "PA_DCHECK_IS_ON", "USE_PARTITION_ALLOC",
               "ENABLE_BACKUP_REF_PTR_SUPPORT", "USE_RAW_PTR_BACKUP_REF_IMPL",
               "ENABLE_GWP_ASAN_SUPPORT"}
    # These fixture flags permit component compilation with the existing
    # mingw toolchain. They are not the Steam CEF GN build configuration.
    content = '#pragma once\n#include "partition_alloc/buildflag.h"\n'
    content += "".join(
        f"#define PA_BUILDFLAG_INTERNAL_{name}() ({int(name in enabled)})\n"
        for name in sorted(flags))
    for name in ("partition_alloc_buildflags.h", "chromecast_buildflags.h",
                 "chromeos_buildflags.h", "raw_ptr_buildflags.h",
                 "partition_alloc_base/debug/debugging_buildflags.h"):
        header = generated / "partition_alloc" / name
        header.parent.mkdir(parents=True, exist_ok=True)
        header.write_text(content)
    geometry = work / "windows-geometry.cc"
    geometry.write_text(f"#define EXPECTED_GIB {expected_gib}\n" + r'''
#include "partition_alloc/partition_address_space.h"
#include "partition_alloc/reservation_offset_table.h"
using namespace partition_alloc::internal;
static_assert(kPoolMaxSize == size_t{EXPECTED_GIB} * kGiB);
static_assert(kMaxSuperPagesInPool == EXPECTED_GIB * 512);
static_assert(PartitionAddressSpace::RegularPoolBaseMask() == ~(kPoolMaxSize - 1));
static_assert(PartitionAddressSpace::BRPPoolBaseMask() == ~(kPoolMaxSize - 1));
static_assert(ReservationOffsetTable::kReservationOffsetTableCoverage == kPoolMaxSize);
static_assert(ReservationOffsetTable::kReservationOffsetTableLength == EXPECTED_GIB * 512);
static_assert(PartitionAddressSpace::ConfigurablePoolMaxSize() == kPoolMaxSize);
static_assert(PartitionAddressSpace::ConfigurablePoolMinSize() == kGiB);
''')
    units = [source / "partition_alloc" / name for name in
             ("address_pool_manager.cc", "partition_address_space.cc",
              "reservation_offset_table.cc")]
    units.append(geometry)
    for unit in units:
        subprocess.run([compiler, "-std=c++20", "-O1",
                        "-DIS_PARTITION_ALLOC_IMPL=1", "-I" + str(source),
                        "-I" + str(chromium_src), "-I" + str(generated),
                        "-c", str(unit), "-o", str(work / (unit.name + ".obj"))],
                       check=True)
        print("PASS Windows x64 component compile", unit.name, flush=True)


PREFIX = r'''
#include <algorithm>
#include <array>
#include <bit>
#include <bitset>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <random>
#include <vector>
#define PA_BUILDFLAG(flag) PA_FLAG_##flag
#define BUILDFLAG(flag) PLATFORM_##flag
#define PA_FLAG_HAS_64_BIT_POINTERS 1
#define PA_FLAG_PA_DCHECK_IS_ON 1
#define PA_FLAG_ENABLE_THREAD_ISOLATION 0
#define PA_GUARDED_BY(lock)
#define PA_CHECK(condition) assert(condition)
#define PA_DCHECK(condition) assert(condition)
#define PA_NOTREACHED() assert(false)
using Lock = std::mutex;
using ScopedGuard = std::lock_guard<Lock>;
struct PoolStats;
constexpr size_t kGiB = size_t{1} << 30;
'''

SUFFIX = r'''
bool has_free_run(const std::vector<bool>& used, size_t length) {
  size_t run = 0;
  for (bool occupied : used) {
    run = occupied ? 0 : run + 1;
    if (run == length) return true;
  }
  return false;
}

int main() {
  static_assert(kPoolMaxSize == EXPECTED_GIB * kGiB);
  static_assert(kMaxSuperPagesInPool == kPoolMaxSize / kSuperPageSize);
  static_assert(Geometry::kReservationOffsetTableCoverage == kPoolMaxSize);
  static_assert(Geometry::kReservationOffsetTableLength == kMaxSuperPagesInPool);
  static_assert(Geometry::kConfigurablePoolMinSize <= Geometry::kConfigurablePoolMaxSize);
  constexpr uintptr_t base = uintptr_t{0x7000000000};
  assert((base & Geometry::kRegularPoolOffsetMask) == 0);
  assert(((base + kPoolMaxSize - 1) & Geometry::kRegularPoolBaseMask) == base);
  assert(((base + kPoolMaxSize) & Geometry::kRegularPoolBaseMask) != base);
  assert((base & Geometry::kBRPPoolOffsetMask) == 0);
  assert(((base + kPoolMaxSize - 1) & Geometry::kBRPPoolBaseMask) == base);

  Pool pool;
  pool.Initialize(base, kPoolMaxSize);
  for (size_t page = 0; page < kMaxSuperPagesInPool; ++page) {
    assert(pool.FindChunk(kSuperPageSize) == base + page * kSuperPageSize);
  }
  assert(pool.FindChunk(kSuperPageSize) == 0);
  assert(!pool.TryReserveChunk(base + kPoolMaxSize, kSuperPageSize));
  pool.FreeChunk(base + kPoolMaxSize - kSuperPageSize, kSuperPageSize);
  assert(pool.FindChunk(2 * kSuperPageSize) == 0);
  assert(pool.FindChunk(kSuperPageSize) == base + kPoolMaxSize - kSuperPageSize);
  pool.FreeChunk(base, kPoolMaxSize);
  assert(pool.FindChunk(kPoolMaxSize) == base);
  assert(pool.FindChunk(kSuperPageSize) == 0);
  pool.FreeChunk(base, kPoolMaxSize);

  assert(pool.TryReserveChunk(base + kSuperPageSize, kSuperPageSize));
  assert(!pool.TryReserveChunk(base, 2 * kSuperPageSize));
  assert(!pool.TryReserveChunk(base + kSuperPageSize, kSuperPageSize));
  pool.FreeChunk(base + kSuperPageSize, kSuperPageSize);

  std::vector<bool> used(kMaxSuperPagesInPool, false);
  std::vector<std::pair<uintptr_t, size_t>> allocations;
  std::mt19937 random(126);
  for (size_t step = 0; step < 10000; ++step) {
    if (!allocations.empty() && random() % 3 == 0) {
      size_t index = random() % allocations.size();
      auto [address, pages] = allocations[index];
      pool.FreeChunk(address, pages * kSuperPageSize);
      size_t offset = (address - base) / kSuperPageSize;
      for (size_t page = offset; page < offset + pages; ++page) {
        assert(used[page]);
        used[page] = false;
      }
      allocations.erase(allocations.begin() + index);
    } else {
      size_t pages = 1 + random() % 64;
      bool available = has_free_run(used, pages);
      uintptr_t address = pool.FindChunk(pages * kSuperPageSize);
      assert(bool(address) == available);
      if (address) {
        size_t offset = (address - base) / kSuperPageSize;
        assert(offset + pages <= used.size());
        for (size_t page = offset; page < offset + pages; ++page) {
          assert(!used[page]);
          used[page] = true;
        }
        allocations.emplace_back(address, pages);
      }
    }
  }
  std::bitset<kMaxSuperPagesInPool> actual;
  pool.GetUsedSuperPages(actual);
  for (size_t page = 0; page < used.size(); ++page) {
    assert(actual[page] == used[page]);
  }

  std::array<Pool, 4> independent;
  for (size_t index = 0; index < independent.size(); ++index) {
    uintptr_t pool_base = base + index * 2 * kPoolMaxSize;
    independent[index].Initialize(pool_base, kPoolMaxSize);
    assert(independent[index].FindChunk(kPoolMaxSize) == pool_base);
    assert(independent[index].FindChunk(kSuperPageSize) == 0);
  }
  std::cout << "PASS " << EXPECTED_GIB << " GiB, " << kMaxSuperPagesInPool
            << " superpages, masks/offset tables/exhaustion/reuse/10000 operations\n";
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chromium_src", type=Path)
    parser.add_argument("--cxx", default="clang++")
    parser.add_argument("--windows-cxx", help="Optional Windows x64 C++ cross compiler")
    parser.add_argument("--baseline", action="store_true",
                        help="Expect unmodified Chromium Windows pool sizes")
    args = parser.parse_args()
    source_dir = args.chromium_src / "base/allocator/partition_allocator/src/partition_alloc"
    fixture = generate_fixture(source_dir)
    # These configurations exercise the selector and pure pool algorithms.
    # The compiler and C++ pointer type remain those of the host.
    windows_gib = 16 if args.baseline else 4
    compressed_windows_gib = 8 if args.baseline else 4
    cases = [("win64", 1, 1, 0, 0, 0, windows_gib),
             ("win-arm64", 1, 0, 0, 0, 0, 16),
             ("desktop", 0, 1, 0, 0, 0, 16),
             ("android", 0, 0, 1, 0, 0, 8),
             ("ios", 0, 0, 0, 1, 0, 8),
             ("compressed-desktop", 0, 1, 0, 0, 1, 8),
             ("compressed-win64", 1, 1, 0, 0, 1, compressed_windows_gib)]
    with tempfile.TemporaryDirectory(prefix="mdeck-cef-pools-") as temporary:
        work = Path(temporary)
        source = work / "pool.cc"
        source.write_text(fixture)
        for name, windows, x64, android, ios, compression, expected in cases:
            executable = work / name
            command = [args.cxx, "-std=c++20", "-O1", "-g",
                       "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                       "-DPLATFORM_IS_WIN=" + str(windows),
                       "-DPLATFORM_IS_ANDROID=" + str(android),
                       "-DPLATFORM_IS_IOS=" + str(ios),
                       "-DPA_FLAG_ENABLE_POINTER_COMPRESSION=" + str(compression),
                       "-DEXPECTED_GIB=" + str(expected)]
            if x64:
                command.append("-DARCH_CPU_X86_64=1")
            subprocess.run(command + [str(source), "-o", str(executable)], check=True)
            print(name, flush=True)
            subprocess.run([str(executable)], check=True)
        if args.windows_cxx:
            compile_windows_components(args.chromium_src, work, args.windows_cxx,
                                       windows_gib)
    print("PASS extracted Chromium pool regression. Full CEF and OS reservations untested.")


if __name__ == "__main__":
    main()
