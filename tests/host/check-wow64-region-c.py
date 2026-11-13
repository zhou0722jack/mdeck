#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test the applied Madeira FEX patch, actual allocator and atomic alias helper; no IPA or Wine execution."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
files = ['FEXCore/include/FEXCore/Utils/AllocatorHooks.h',
         'FEXCore/Source/Utils/ArchHelpers/Arm64.cpp', 'Source/Windows/WOW64/Module.cpp']
patch = root / 'build/fex-patches/0002-ios-wow64-region-c.patch'
native = (root / 'build/ntdll-unix/virtual_ios.c').read_text()
assert 'int low_ok = ios_jit_low_size_global != 0;' in native
assert 'int low_ok = ios_jit_low_size_global && !ios_wow_base();' not in native
assert '"build/fex-patches/**"' in (root / 'tools/build/runtime-components.json').read_text()

memory_api = r'''
#pragma once
#include <cstddef>
#include <cstdint>
using DWORD = unsigned long;
constexpr DWORD MEM_COMMIT=0x1000, MEM_RESERVE=0x2000, MEM_TOP_DOWN=0x100000, MEM_RELEASE=0x8000, MEM_DECOMMIT=0x4000;
constexpr DWORD PAGE_NOACCESS=1, PAGE_READONLY=2, PAGE_READWRITE=4, PAGE_EXECUTE_READ=0x20, PAGE_EXECUTE_READWRITE=0x40;
constexpr unsigned MemExtendedParameterAddressRequirements=1, MemExtendedParameterAttributeFlags=5;
constexpr uint64_t MEM_EXTENDED_PARAMETER_EC_CODE=0x40;
struct MEM_ADDRESS_REQUIREMENTS { void* LowestStartingAddress; void* HighestEndingAddress; size_t Alignment; };
struct MEM_EXTENDED_PARAMETER { unsigned Type {}; union { void* Pointer; uint64_t ULong64; }; };
struct MEMORY_BASIC_INFORMATION { DWORD Protect; };
void* VirtualAlloc2(void*,void*,size_t,DWORD,DWORD,MEM_EXTENDED_PARAMETER*,unsigned);
int VirtualFree(void*,size_t,DWORD);
void* VirtualAlloc(void*,size_t,DWORD,DWORD);
size_t VirtualQuery(void*,MEMORY_BASIC_INFORMATION*,size_t);
int VirtualProtect(void*,size_t,DWORD,DWORD*);
'''
harness = r'''
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include <limits>
#include <FEXCore/Utils/AllocatorHooks.h>
#include <FEXCore/Utils/DualMap.h>
using FEXCore::Allocator::IOSJIT::Range;
namespace JIT = FEXCore::Allocator::IOSJIT;
constexpr uintptr_t RX=0x148000000ULL, RW=0x7026c94000ULL, C=0x1218e4000ULL;
constexpr size_t PoolSize=0x38000000ULL, CSize=0x1e71c000ULL;
namespace FEXCore::Allocator {
extern "C" {
uintptr_t ios_fex_band_base=0x7c00000000ULL, ios_fex_band_end=0x8000000000ULL;
#ifndef ARCHITECTURE_arm64ec
uintptr_t ios_fex_jit_pool_rx=RX, ios_fex_jit_pool_end=RX+PoolSize;
IOSJIT::Range ios_fex_jit_low_region {};
#endif
}
}
namespace FEXCore::DualMap { int64_t WriteOffset=RW-RX; }
static void* nextAllocation;
static unsigned released;
void* VirtualAlloc2(void*,void*,size_t,DWORD,DWORD protection,MEM_EXTENDED_PARAMETER* parameters,unsigned count) {
  assert(protection==PAGE_EXECUTE_READWRITE && count==1 && parameters->ULong64==MEM_EXTENDED_PARAMETER_EC_CODE);
  return nextAllocation;
}
int VirtualFree(void*,size_t,DWORD flags) { assert(flags==MEM_RELEASE); ++released; return 1; }
extern "C" uint64_t IosMonoResolveRW(uint64_t address,uint64_t) {
  return address==0x7400000000ULL ? 0x7500000000ULL : 0;
}
ATOMIC_HELPER
int main(int argc,char**) {
  const bool withC=argc==1;
  setenv("WINE_IOS_JIT_RX","148000000",1);
  setenv("WINE_IOS_JIT_SIZE","38000000",1);
  setenv("WINE_IOS_JIT_RW","7026c94000",1);
  if(withC) setenv("WINE_IOS_JIT_TAIL_REGION","1218e4000:1e71c000",1);
  else unsetenv("WINE_IOS_JIT_TAIL_REGION");
  const Range main{RX,PoolSize};
  Range low;
  assert(JIT::ParseLow("1218e4000:1e71c000",main,RW,low) && low.Base==C && low.Size==CSize);
  assert(JIT::ParseLow("0x1218e4000:0x1e71c000",main,RW,low));
  for(const char* bad : {"1218e4001:1e71c000","1218e4000:1e71c001","1218e4000:1000",
                        "1218e4000:1e71c000junk","1218e4000:","1218e4000","-1:1000000",
                        "1218e4000:ffffffffffffffff","ffffffffffffc000:1000000",
                        "148000000:1000000","147000000:2000000","12345678901234567:1000000"}) {
    assert(!JIT::ParseLow(bad,main,RW,low) && !low.Base && !low.Size);
  }
  assert(!JIT::ParseLow("1218e4000:1e71c000",main,1,low));
  assert(JIT::ParseLow(nullptr,main,RW,low) && !low.Size);
  assert(JIT::ParseLow("",main,RW,low) && !low.Size);
  assert(JIT::ParseLow(withC ? "1218e4000:1e71c000" : nullptr,main,RW,low));
#ifndef ARCHITECTURE_arm64ec
  FEXCore::Allocator::ios_fex_jit_low_region=low;
#endif
  assert(main.Contains(RX,PoolSize) && main.Contains(RX+PoolSize-1,1));
  assert(!main.Contains(RX+PoolSize,1) && !main.Contains(RX+PoolSize-1,2));
  assert(!main.Contains(RX,0) && !main.Contains(RX,std::numeric_limits<size_t>::max()));
  assert(!JIT::Allowed(main,low,0x140000000ULL,0x4000)); // executable window
  assert(!JIT::Allowed(main,low,RW,0x4000)); // writable view is not executable code
  assert(!JIT::Allowed(main,low,C,static_cast<size_t>(RX-C)+0x4000)); // spans C/window/main
  assert(!JIT::Allowed(main,low,std::numeric_limits<uintptr_t>::max()-0x3fff,0x8000));
  auto allocate=[](uintptr_t address,size_t bytes) {
    nextAllocation=reinterpret_cast<void*>(address);
    return FEXCore::Allocator::VirtualAlloc(bytes,true);
  };
  assert(allocate(RX,0x4000)==reinterpret_cast<void*>(RX));
  if(withC) assert(allocate(C,0x8000000)==reinterpret_cast<void*>(C));
#ifndef ARCHITECTURE_arm64ec
  unsigned before=released;
  if(!withC) assert(!allocate(C,0x4000));
  assert(!allocate(0x140000000ULL,0x4000));
  assert(!allocate(C+CSize-0x4000,0x8000));
  assert(!allocate(RX+PoolSize-0x4000,0x8000));
  assert(!allocate(std::numeric_limits<uintptr_t>::max()-0x3fff,0x8000));
  assert(released==before+(withC?4:5));
#endif
  assert(IosAtomicWritableAlias(RX,16)==RW);
  assert(IosAtomicWritableAlias(C,16)==(withC?C+(RW-RX):C));
  assert(IosAtomicWritableAlias(C+CSize-8,16)==C+CSize-8);
  assert(IosAtomicWritableAlias(RX+PoolSize-8,16)==RX+PoolSize-8);
  assert(IosAtomicWritableAlias(0x140000000ULL,16)==0x140000000ULL);
  assert(IosAtomicWritableAlias(0x7400000000ULL,16)==0x7500000000ULL);
  assert(IosAtomicWritableAlias(std::numeric_limits<uintptr_t>::max()-7,16)==std::numeric_limits<uintptr_t>::max()-7);
  std::puts(withC ? "PASS: C accepted, main retained, executable window/RW/overflow rejected, atomic aliases bounded"
                  : "PASS: C absent keeps main-pool allocation and anonymous-alias fallback");
}
'''
with tempfile.TemporaryDirectory(prefix='mdeck-wow64-c-') as tmp:
    folder=Path(tmp)
    # Apply the actual shipped patch to copies of the pinned files. Leave the
    # checked-out FEX tree pristine, and do not run either FEX build script.
    subprocess.run(['git','init','-q',str(folder)],check=True)
    for name in files:
        destination=folder/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes((root/'FEX'/name).read_bytes())
    subprocess.run(['git','-C',str(folder),'apply','--check',str(patch)],check=True)
    subprocess.run(['git','-C',str(folder),'apply',str(patch)],check=True)
    hooks=(folder/files[0]).read_text()
    module=(folder/files[2]).read_text()
    assert 'IOSJIT::Allowed(Main, ios_fex_jit_low_region, Addr, Size)' in hooks
    assert module.index('IOSJIT::ParseLow(low_env') < module.index('CTX->InitCore();')
    assert 'invalid region C; JIT initialization refused' in module
    arm=(folder/files[1]).read_text()
    start=arm.index('static uint64_t IosAtomicWritableAlias(')
    end=arm.index('\n}\n#endif',start)+2
    atomic=arm[start:end]
    include=folder/'include'
    deps=include/'FEXCore/Utils'
    deps.mkdir(parents=True)
    (deps/'CompilerDefs.h').write_text('#pragma once\n#define FEX_DEFAULT_VISIBILITY\n')
    (deps/'EnumOperators.h').write_text('#pragma once\n#define FEX_DEF_NUM_OPS(T) constexpr T operator|(T a,T b) { return static_cast<T>(static_cast<unsigned>(a)|static_cast<unsigned>(b)); }\n')
    (deps/'LogManager.h').write_text('#pragma once\nnamespace LogMan::Msg { template<class... T> void EFmt(const char*,T...) {} }\n#define LOGMAN_MSG_A_FMT(...) ((void)0)\n')
    (include/'memoryapi.h').write_text(memory_api)
    for name in ['IOSJITRegions.h','DualMap.h']:
        source=folder/'FEXCore/include/FEXCore/Utils'/name
        if not source.exists(): source=root/'FEX/FEXCore/include/FEXCore/Utils'/name
        (deps/name).write_bytes(source.read_bytes())
    (deps/'AllocatorHooks.h').write_text(hooks)
    program=folder/'Check.cpp'
    program.write_text(harness.replace('ATOMIC_HELPER',atomic))
    for architecture in ['wow64','arm64ec']:
        binary=folder/architecture
        command=['xcrun','clang++','-std=c++20','-O1','-g','-D_WIN32','-DFEX_IOS_HOST',
                 '-fsanitize=address,undefined','-fno-sanitize-recover=all','-I',str(include),str(program),'-o',str(binary)]
        if architecture=='arm64ec': command.append('-DARCHITECTURE_arm64ec')
        subprocess.run(command,check=True)
        subprocess.run([str(binary)],check=True)
        subprocess.run([str(binary),'without-C'],check=True)
print('PASS: actual patched allocator/atomic helper in both compile branches; C metadata and source integration checked')
print('UNRUN: full xtajit PE builds, actual iOS execution, cache churn reduction and Steam performance acceptance')
