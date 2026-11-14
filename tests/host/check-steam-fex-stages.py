#!/usr/bin/env python3
"""Run in Actions: real bridge/RAII behavior and applied patch integration.
No IPA, no Wine execution, no product runtime builds.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile

assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Run this check in GitHub Actions'
root = Path(__file__).resolve().parents[2]
patches = root / 'build/fex-patches'
program = r'''
#include <cassert>
#include <cstdio>
#include <atomic>
#include <thread>
#include <vector>
#include "steam_probe_abi.h"
// The fixture runs on macOS: load its standard library first, then select
// the exact PE-only probe code without changing libc++'s platform headers.
#define _WIN32 1
#include "SteamProbe.h"
#undef _WIN32
static sf_bridge b {};
alignas(16) static uint64_t teb[32] {};
extern "C" uint64_t mdeck_steam_probe_teb() { return reinterpret_cast<uintptr_t>(teb); }
static unsigned tid=0x23c;
static uint64_t address() { return reinterpret_cast<uintptr_t>(teb); }
static sf_ticket enter(unsigned stage) { return sf_enter(&b,address(),tid,stage); }
static void reset(uint64_t epoch) {
  __atomic_store_n(&b.active_epoch,epoch,__ATOMIC_RELEASE);
  assert(sf_enroll(&b,epoch,address(),100,0xe8,tid));
}
int main() {
  static_assert(sizeof(sf_metric)==32 && offsetof(sf_slot,metric)==40);
  static_assert(sizeof(sf_slot)==232 && offsetof(sf_bridge,slots)==48);
  static_assert(__atomic_always_lock_free(8,nullptr));
  b.magic=SF_MAGIC;b.bytes=sizeof(b);b.frequency=24000000;
  teb[0x48/8]=tid;
  assert(!enter(SF_COMPILE).slot);
  reset(7);
  assert(!sf_enroll(&b,7,address(),100,0xe8,0));
  assert(!sf_enroll(&b,7,address(),101,0xe8,tid+4));
  assert(!sf_enter(&b,address(),tid+4,SF_COMPILE).slot);
  auto t=enter(SF_COMPILE);assert(t.slot);
  auto* slot=t.slot;
  sf_leave(&b,t,100,160);
  sf_leave(&b,enter(SF_COMPILE),100,130);
  assert(slot->metric[SF_COMPILE].calls==2 && slot->metric[SF_COMPILE].samples==2);
  assert(slot->metric[SF_COMPILE].ticks==90 && slot->metric[SF_COMPILE].max_ticks==60);
  for(unsigned i=0;i<128;i++)sf_leave(&b,enter(SF_LOOKUP),100,110);
  assert(slot->metric[SF_LOOKUP].calls==128 && slot->metric[SF_LOOKUP].samples==2 && slot->metric[SF_LOOKUP].ticks==20);
  // No wait when recursively interrupted while a recorder owns this gate.
  assert(sf_lock(slot));assert(!enter(SF_COMPILE).slot);sf_unlock(slot);
  t=enter(SF_COMPILE);assert(sf_lock(slot));sf_leave(&b,t,0,20);sf_unlock(slot);
  assert(b.dropped==2);
  // In-flight old epoch and manual stop cannot contaminate the next session.
  t=enter(SF_COMPILE);__atomic_store_n(&b.active_epoch,0,__ATOMIC_RELEASE);
  sf_leave(&b,t,0,1000);assert(!enter(SF_COMPILE).slot);
  reset(8);sf_leave(&b,t,0,1000);assert(slot->metric[SF_COMPILE].ticks==0);
  assert(!sf_enroll(&b,7,address(),100,0xe8,tid));
  // A reversed clock does not record an overflowing duration.
  sf_leave(&b,enter(SF_CLEAR),200,100);assert(slot->metric[SF_CLEAR].samples==0);
  // Fill the bounded collision chain without evicting its first owner.
  sf_bridge collisions {};collisions.active_epoch=1;
  unsigned used=0;
  for(uint64_t a=0x7200010000ull;used<5;a+=0x1000)if(sf_hash(a)==0) {
    int ok=sf_enroll(&collisions,1,a,used+1,1,used+1);
    assert(ok==(used<4));used++;
  }
  // Concurrent producers and the real nonblocking snapshot lock.
  reset(9);
  std::atomic<bool> done {false};
  std::thread reader([&] {
    while(!done.load())if(sf_lock(slot)) {
      auto m=slot->metric[SF_COMPILE];
      assert(m.samples<=m.calls && m.ticks==m.samples*10);
      sf_unlock(slot);
    }
  });
  std::vector<std::thread> workers;
  for(unsigned k=0;k<4;k++)workers.emplace_back([&] {
    for(unsigned i=0;i<10000;i++)sf_leave(&b,enter(SF_COMPILE),0,10);
  });
  for(auto& w:workers)w.join();
  done=true;reader.join();
  assert(slot->metric[SF_COMPILE].samples>0 && slot->metric[SF_COMPILE].calls<=40000);
  // Compile and exercise the exact PE-facing RAII, not a fixture substitute.
  FEXCore::SteamProbe::Initialize(nullptr,1);
  FEXCore::SteamProbe::Initialize("garbage",1);
  FEXCore::SteamProbe::Initialize("fffffffffffffffff",1);
  assert(!FEXCore::SteamProbe::Bridge);
  char pointer[32];snprintf(pointer,sizeof(pointer),"%llx",(unsigned long long)(uintptr_t)&b);
  FEXCore::SteamProbe::Initialize(pointer,1);
  FEXCore::SteamProbe::Initialize(pointer,2);
  assert(FEXCore::SteamProbe::Bridge==&b && b.attached==3);
  reset(10);
  auto early=[] { MDECK_STEAM_SCOPE(SF_COMPILE); return 1; };
  assert(early()==1 && slot->metric[SF_COMPILE].samples==1);
  try { MDECK_STEAM_SCOPE(SF_CLEAR);throw 1; } catch(int) {}
  assert(slot->metric[SF_CLEAR].samples==1);
  { MDECK_STEAM_SCOPE(SF_MIGRATE);__atomic_store_n(&b.active_epoch,0,__ATOMIC_RELEASE); }
  assert(slot->metric[SF_MIGRATE].samples==0);
  puts("PASS production FEX bridge/RAII: default off, stride, counts/max, nonblocking reentry, drops, epoch cancellation, collision bound, concurrent snapshots, early returns");
}
'''

with tempfile.TemporaryDirectory(prefix='mdeck-steam-stages-') as tmp:
    work = Path(tmp)
    subprocess.run(['git','init','-q',str(work)],check=True)
    # Copies of the pin; neither the local submodule nor the pin is modified.
    names = set()
    for patch in patches.glob('*.patch'):
        names.update(re.findall(r'^--- a/(.+)$', patch.read_text(), re.M))
    for name in names:
        target = work/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(subprocess.check_output(['git','-C',str(root/'FEX'),'show','HEAD:'+name]))
    for patch in sorted(patches.glob('*.patch')):
        subprocess.run(['git','-C',str(work),'apply','--check',str(patch)],check=True)
        subprocess.run(['git','-C',str(work),'apply',str(patch)],check=True)
    subprocess.run(['git','-C',str(work),'apply','--reverse','--check',str(patches/'0003-steam-hotspot-stages.patch')],check=True)
    dep = work/'FEXCore/include/FEXCore/Utils'
    dep.mkdir(parents=True,exist_ok=True)
    for header in ['SteamProbe.h','steam_probe_abi.h','SteamCompileReason.h','steam_compile_reason_abi.h']:
        shutil.copyfile(patches/header,dep/header)
    # Executable control fixture uses the shipped header in both PE macro paths.
    src=work/'probe.cpp';src.write_text(program)
    for mode in ['wow64','arm64ec']:
        out=work/mode
        command=['xcrun','clang++','-std=c++20','-O1','-g','-Wall','-Wextra','-Werror',
                 '-DFEX_IOS_HOST','-fsanitize=address,undefined','-pthread',
                 '-I'+str(dep),str(src),'-o',str(out)]
        if mode=='arm64ec':command.append('-DARCHITECTURE_arm64ec')
        subprocess.run(command,check=True)
        subprocess.run([str(out)],check=True,timeout=45)
    # Keep hook locations coupled to production methods, including lookup's
    # early return paths and migration/sweep which don't pass through CompileCode.
    contracts={
        'FEXCore/Source/Interface/Core/Core.cpp':[
            ('ContextImpl::CompileCode(', 'MDECK_STEAM_SCOPE(SF_COMPILE);'),
            ('ContextImpl::CompileBlock(', 'MDECK_STEAM_SCOPE(SF_DISPATCH);')],
        'FEXCore/Source/Interface/Core/LookupCache.h':[
            ('void ChangeGuestToHostMapping(', 'MDECK_STEAM_SCOPE(SF_MIGRATE);'),
            ('uintptr_t FindBlock(', 'MDECK_STEAM_SCOPE(SF_LOOKUP);')],
        'FEXCore/Source/Interface/Core/JIT/JIT.cpp':[
            ('void Arm64JITCore::ClearCache()', 'MDECK_STEAM_SCOPE(SF_CLEAR);')],
        'FEXCore/Source/Interface/Core/LookupCache.cpp':[
            ('void LookupCache::ClearCache(', 'MDECK_STEAM_SCOPE(SF_CLEAR);')],
        'FEXCore/Source/Interface/Core/CPUBackend.cpp':[
            ('void IosMaybeSweepCodeBuffers(', 'MDECK_STEAM_SCOPE(SF_SWEEP);')],
    }
    for path,pairs in contracts.items():
        source=(work/path).read_text()
        for method,hook in pairs:
            start=source.index(method)
            opening=source.index('{',start)
            assert source[opening+1:].lstrip().startswith(hook), (path,method)
    for mode,teb,path in [('WOW64','CurrentTEB()',1),('ARM64EC','IOSLoadTEB()',2)]:
        text=(work/f'Source/Windows/{mode}/Module.cpp').read_text()
        assert f'Initialize(getenv("MADEIRA_STEAM_FEX_BRIDGE"), {path});' in text
        assert f'return reinterpret_cast<uint64_t>({teb});' in text
    # A native/non-PE FEX translation unit must not acquire PE dependencies.
    noop=work/'noop.cpp';noop.write_text('#include "SteamProbe.h"\nint main(){MDECK_STEAM_SCOPE(SF_COMPILE);}\n')
    subprocess.run(['xcrun','clang++','-std=c++20','-Wall','-Wextra','-Werror',
                    '-I'+str(dep),str(noop),'-o',str(work/'noop')],check=True)
    subprocess.run([str(work/'noop')],check=True)

print('PASS: all shipped FEX patches apply together; both PE hook paths and native no-op checked')
print('UNRUN: full PE runtime build/link, physical iOS counter/ABI behavior, Steam workload overhead')
