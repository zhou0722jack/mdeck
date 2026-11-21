#!/usr/bin/env python3
"""Actions-only: dual-segment policy/lifetime and production source contracts."""
import os
import re
import subprocess
import tempfile
from pathlib import Path

assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Run only in GitHub Actions'
root = Path(__file__).resolve().parents[2]
patches = root / 'build/fex-patches'
chain = sorted(patches.glob('*.patch'))

def method(source, signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

with tempfile.TemporaryDirectory(prefix='mdeck-dual-segments-') as tmp:
    work = Path(tmp)
    src = work / 'source'
    src.mkdir()
    subprocess.run(['git', 'init', '-q', str(src)], check=True)
    for name in set(re.findall(r'^--- a/(.+)$', ''.join(p.read_text() for p in chain), re.M)):
        out = src / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(subprocess.check_output(['git', '-C', str(root / 'FEX'), 'show', 'HEAD:' + name]))
    for patch in chain:
        subprocess.run(['git', '-C', str(src), 'apply', str(patch)], check=True)

    base = src / 'FEXCore/Source/Interface/Core'
    lookup = (base / 'LookupCache.h').read_text()
    # Exercise the production L3 bodies with controlled lock/container adapters.
    map_methods = '\n'.join(method(lookup, signature) for signature in (
        '  const BlockEntry& AddBlockMapping(', '  const BlockEntry* FindBlock(',
        '  bool MatchesCodeSegment(', '  bool Erase(', '  void InvalidateRange(',
        '  bool AddBlockExecutableRange(',
    ))
    fixture = work / 'dual.cpp'
    fixture.write_text(r'''
#include <cassert>
#include <array>
#include <cstdint>
#include <limits>
#include <map>
#include <memory>
#include <ranges>
#include <string_view>
#include <vector>
#define FEX_IOS_HOST 1
#define _WIN32 1
#include "DualCodeSegments.h"
using namespace FEXCore::MDeckSegments;
constexpr uintptr_t First = 0x150000000ull, Tail = 0x158000000ull, Low = 0x110000000ull;
constexpr std::size_t Guard = 4096;
namespace fextl { template<class T> using vector = std::vector<T>; }
struct LookupCacheReadLockToken {};
struct LookupCacheWriteLockToken {};
namespace FEXCore::Context { using ExitFunctionLinkData = uintptr_t; }
struct MapFixture {
  struct BlockEntry { uint64_t HostCode; fextl::vector<uint64_t> CodePages; bool MDeckNormal; uint8_t MDeckCodeSegment; };
  struct BlockLinkTag {
    uint64_t GuestDestination;
    uintptr_t* HostLink;
    bool operator<(const BlockLinkTag& Other) const {
      return GuestDestination == Other.GuestDestination
        ? reinterpret_cast<uintptr_t>(HostLink) < reinterpret_cast<uintptr_t>(Other.HostLink)
        : GuestDestination < Other.GuestDestination;
    }
  };
  std::map<uint64_t, BlockEntry> BlockList;
  std::map<uint64_t, fextl::vector<uint64_t>> CodePages;
  std::map<BlockLinkTag, void(*)(uintptr_t*)> Links;
  decltype(Links)* BlockLinks = &Links;
  LookupCacheWriteLockToken AcquireWriteLock() { return {}; }
  @MAP_METHODS@
};
unsigned allocations, frees, ids;
bool fail;
void* Allocate(std::size_t size) {
  assert(size == Bytes && Reserved == 1 && ActiveSecondRX == 0);
  ++allocations;
  return fail ? nullptr : reinterpret_cast<void*>(Tail);
}
void Free(void* ptr, std::size_t size) {
  assert(reinterpret_cast<uintptr_t>(ptr) == Tail && size == Bytes);
  assert(Reserved == 1 && ActiveSecondRX == 0);
  ++frees;
}
uint64_t Id() { return ++ids; }
BudgetOwner released;
void ReportRelease(const BudgetOwner& owner) {
  assert(!Reserved && !ReadBudgetOwner().Generation);
  released = owner;
}
int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string_view mode = argv[1];
  const bool on = mode == "on";
  const char* value = mode == "default" ? nullptr : mode == "invalid" ? "10" : "1";
  const char* low = mode == "bad-pool" ? "14fff0000:10000000" : "110000000:18000000";
  assert(Configure(value, mode != "other", "150000000", "20000000", "180000000", low) == on);
  assert(Enabled() == on);
  assert(Configure(on ? "0" : "1", true, "150000000", "20000000", "180000000", "110000000:18000000") == on);
  if (!on) return 0;
  assert(PoolContains(First, Bytes) && PoolContains(Tail, Bytes) && PoolContains(Low, Bytes));
  assert(!PoolContains(Low + 0x14000000, Bytes) && !PoolContains(First - 0x4000, Bytes));
  assert(!PoolContains(First, 0) && !PoolContains(UINTPTR_MAX - 1, Bytes));
  assert(Fits(Bytes - Guard, 16, Bytes - Guard - 16));
  assert(!Fits(Bytes - Guard, 16, Bytes - Guard - 15));
  assert(!Fits(Bytes, SIZE_MAX, 1));
  auto current = std::make_shared<SecondSegment>();
  auto thread = current;
  auto exception = current;
  assert(!current->Address() && !allocations && !Reserved);
  assert(current->TryAttach(Bytes - Guard + 1, Guard, Allocate, Free, Id) == Append::TooLarge);
  assert(!allocations && !ids);
  fail = true;
  assert(current->TryAttach(16, Guard, Allocate, Free, Id) == Append::AllocationFailed);
  assert(!current->Address() && !ActiveSecondRX && !Reserved && !ids && !frees);
  assert(!ReadBudgetOwner().Generation);
  fail = false;
  assert(current->TryAttach(16, Guard, Allocate, Free, Id, {0xe8, 3, 10, 0, First, 0}, ReportRelease) == Append::Added);
  assert(current->Address() == Tail && ActiveSecondRX == Tail && current->Generation == 1 && !current->Offset);
  const auto firstOwner = ReadBudgetOwner();
  assert(firstOwner.PID == 0xe8 && firstOwner.Manager == 3 && firstOwner.PrimaryGeneration == 10);
  assert(firstOwner.Generation == 1 && firstOwner.PrimaryRX == First && firstOwner.SecondRX == Tail);
  {
    MapFixture map;
    const LookupCacheWriteLockToken write;
    const LookupCacheReadLockToken read;
    constexpr uint64_t one = 0x401000, two = 0x403000, keep = 0x408000, sharedPage = 0x500000;
    const auto add = [&](uint64_t rip, uintptr_t host, uint8_t segment, uint64_t page) {
      map.AddBlockMapping(rip, {page}, reinterpret_cast<void*>(host), write, true, segment);
      map.AddBlockExecutableRange(std::array{rip}, page, Guard, write);
    };
    add(one, First + 16, 0, sharedPage);
    add(two, Tail + 16, 1, sharedPage);
    add(keep, Tail + 32, 1, sharedPage + Guard);
    assert(map.FindBlock(one, read)->HostCode == First + 16);
    assert(map.FindBlock(two, read)->HostCode == Tail + 16);
    assert(map.MatchesCodeSegment(one, First + 16, 0, write));
    assert(map.MatchesCodeSegment(two, Tail + 16, 1, write));
    assert(!map.MatchesCodeSegment(two, Tail + 16, 0, write));
    assert(!map.MatchesCodeSegment(one, First + 32, 0, write));
    uintptr_t link1 = First + 16, link2 = Tail + 16;
    const auto delink = +[](uintptr_t* host) { *host = 0; };
    map.BlockLinks->emplace(MapFixture::BlockLinkTag{one, &link1}, delink);
    map.BlockLinks->emplace(MapFixture::BlockLinkTag{two, &link2}, delink);
    map.InvalidateRange(sharedPage, Guard);
    assert(!map.FindBlock(one, read) && !map.FindBlock(two, read) && !link1 && !link2);
    assert(map.FindBlock(keep, read)->HostCode == Tail + 32);
    add(one, Tail + 48, 1, sharedPage);
    assert(!map.MatchesCodeSegment(one, First + 16, 0, write));
    assert(map.MatchesCodeSegment(one, Tail + 48, 1, write));
  }
  assert(Classify(First, Bytes - Guard, Tail, Guard, First) == Segment::First);
  assert(Classify(First, Bytes - Guard, Tail, Guard, Tail) == Segment::Second);
  assert(Classify(First, Bytes - Guard, Tail, Guard, Tail + Bytes - Guard - 1) == Segment::Second);
  for (auto pc : {First - 1, Tail - 1, Tail + Bytes - Guard, Tail + Bytes, uintptr_t{0}})
    assert(Classify(First, Bytes - Guard, Tail, Guard, pc) == Segment::Outside);
  current->Offset = Bytes - Guard;
  assert(current->TryAttach(16, Guard, Allocate, Free, Id) == Append::AlreadyFull);
  assert(current->Offset == Bytes - Guard && allocations == 2);
  current = std::make_shared<SecondSegment>(); // rollover, with old group pinned
  const BudgetOwner next {0xe8, 3, 11, 0, First + 0x10000000, 0};
  assert(current->TryAttach(16, Guard, Allocate, Free, Id, next, ReportRelease) == Append::Budget);
  assert(ReadBudgetOwner().Generation == 1 && ReadBudgetOwner().PrimaryGeneration == 10);
  thread.reset();
  assert(!frees && !released.Generation && exception->Address() == Tail && Reserved == 1);
  exception.reset();
  assert(frees == 1 && !ActiveSecondRX && !Reserved && !ReadBudgetOwner().Generation);
  assert(released.Generation == 1 && released.PrimaryRX == First && released.SecondRX == Tail);
  assert(current->TryAttach(16, Guard, Allocate, Free, Id, next, ReportRelease) == Append::Added);
  assert(ReadBudgetOwner().Generation == 2 && ReadBudgetOwner().PrimaryGeneration == 11);
  assert(current->Generation == 2 && current->Offset == 0); // reuse the same VA safely
  current.reset();
  assert(frees == 2 && allocations == 3 && !ActiveSecondRX && !Reserved);
  assert(released.Generation == 2 && released.PrimaryRX == next.PrimaryRX);
}
'''.replace('@MAP_METHODS@', map_methods))
    exe = work / 'dual'
    subprocess.run(['xcrun', 'clang++', '-std=c++20', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-O1', '-g', '-I' + str(patches),
                    '-I' + str(src / 'FEXCore/include'), str(fixture), '-o', str(exe)], check=True)
    for mode in ['default', 'invalid', 'other', 'bad-pool', 'on']:
        subprocess.run([str(exe), mode], check=True)

    backend = (base / 'CPUBackend.cpp').read_text()
    backend_h = (base / 'CPUBackend.h').read_text()
    core = (base / 'Core.cpp').read_text()
    jit = (base / 'JIT/JIT.cpp').read_text()
    branch = (base / 'JIT/BranchOps.cpp').read_text()
    append = backend.split('bool CodeBufferManager::TryAppendCodeSegment(', 1)[1].split('#endif', 1)[0]
    assert append.count('VirtualAlloc(Size, true)') == 1 and 'PoolContains(' in append
    assert 'budget_owner={}' in append and 'request_owner={}' in append and 'event=released' in append
    for forbidden in ('LookupCache', 'AllocateNew(', 'IosCodeBufferGenCounter', 'ResetCallRetStack'):
        assert forbidden not in append
    assert 'MDeckSegments::SecondSegment MDeckSecond;' in backend_h
    pc_check = backend.split('bool CPUBackend::IsAddressInCodeBuffer(', 1)[1]
    assert 'Buffer.SegmentForAddress(Address)' in pc_check and 'SignalHandlerCodeBuffers' in pc_check
    count_refs = method(backend, '  int CPUBackend::IosTryCountSegmentReferences(')
    assert 'compare_exchange_strong' in count_refs and 'return -1;' in count_refs
    assert 'Matches(CurrentCodeBuffer)' in count_refs and 'Buffer : SignalHandlerCodeBuffers' in count_refs
    sweep = method(backend, '  extern "C" void IosMaybeSweepCodeBuffers(')
    assert sweep.index('if (*Snap[i].InSim != 0)') < sweep.index('Results[i] = SweepResult::InSimulation')
    assert sweep.index('IosRemoteMigrateStale(Latest)') < sweep.index('Results[i] = static_cast<SweepResult>(Result)')
    assert sweep.index('IosCodeBufferSweepGate, 0') < sweep.index('Sample(*Snap[i].Thread->CPUBackend, Snap[i].TID')
    assert sweep.index('Sample(*Snap[i].Thread->CPUBackend, Snap[i].TID') < sweep.index('IosSweepBusy.store(0')
    assert sweep.index('IosSweepBusy.store(0') < sweep.index('event=reference-snapshot')
    assert sweep.index('IosSweepBusy.store(0') < sweep.index('event=reference-holder')
    assert 'TraceHolders && (Current || Signals)' in sweep and 'HolderCount < MaxHolders' in sweep
    assert 'holders_omitted={}' in sweep and 'retry_left={}' in sweep
    assert backend.count('IosSweepSlots[i].TID = ::GetCurrentThreadId();') == 2
    output = jit.split('const auto TempSize = GetCursorOffset();', 1)[1]
    assert output.index('if (IosUnpubMode)') < output.index('TryAppendCodeSegment(') < output.index('CTX->ClearCodeCache(')
    assert 'IosStampTeb && !IosNestedS' in output
    assert output.index('ActiveCodeGeneration()') < output.index('memcpy(WritePtr(') < output.index('CodeData.MDeckReasonOutput =')
    linker = jit.split('uint64_t Arm64JITCore::ExitFunctionLink(', 1)[1]
    assert linker.index('AcquireWriteLock()') < linker.index('MatchesCodeSegment(') < linker.index('AddBlockLink(')
    assert 'SourceSegment != Group.SegmentForAddress(HostCode)' in linker
    assert 'BlockEntry {(uintptr_t)HostCode, CodePages, MDeckNormal, MDeckCodeSegment}' in lookup
    assert '->InvalidateRange(Start, Length)' in core
    assert 'MDeckCodeSegment);' in core and 'AddBlockExecutableRange(' in lookup
    guard = branch.split('if (MDeckSegments::Enabled())', 1)[1].split('ldr(TMP2, STATE, offsetof(FEXCore::Core::CpuStateFrame, Pointers.DispatcherLoopTop));', 1)[0]
    for token in ('&MDeckSegments::ActiveSecondRX', 'ldar(TMP1, TMP1)', 'adr(TMP3, &Here)', 'cbnz(ARMEmitter::Size::i64Bit, TMP1, &SkipFullLookup)', 'cbz(ARMEmitter::Size::i64Bit, TMP1, &SkipFullLookup)'):
        assert token in guard
    for path in ['WOW64', 'ARM64EC']:
        mod = (src / f'Source/Windows/{path}/Module.cpp').read_text()
        assert mod.index('MDeckSegments::Configure(') < mod.index('MDeckPrevious::Configure(') < mod.index('CTX->InitCore();')
        assert 'CEF && Compatible' in mod and 'CEF && !Segments' in mod
        if path == 'WOW64':
            startup = method(mod, 'void BTCpuProcessInit()')
            assert 'Segments ? getenv("MADEIRA_FEX_DUAL_OWNER_MIGRATION") : nullptr' in startup
            assert startup.index('IosWowOwnerMigrationEnabled =') < startup.index('CTX->InitCore();')
            attempt = method(mod, 'static void IosWowTryOwnerMigration(')
            assert attempt.index('if (IosWowOwnerMigrationEnabled &&') < attempt.index('IosWowMigrateRetiredDualSegment(')
        else:
            assert 'MADEIRA_FEX_DUAL_OWNER_MIGRATION' not in mod
    bridge = (root / 'app/Madeira/WineProcessBridge.m').read_text()
    assert bridge.index('unsetenv("MADEIRA_FEX_DUAL_CODE_SEGMENTS")') < bridge.index('setenv(k.UTF8String, v.UTF8String, 1);')
    assert bridge.index('unsetenv("MADEIRA_FEX_DUAL_OWNER_MIGRATION")') < bridge.index('setenv(k.UTF8String, v.UTF8String, 1);')
    print('PASS dual-segment policy, size/range/budget, pin and reuse lifetime, plus patch integration contracts')
    print('UNRUN by this fixture: PE compilation, emitted ARM64 execution, and concurrent device invalidation/exception behavior')
