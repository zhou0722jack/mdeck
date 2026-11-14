#!/usr/bin/env python3
"""Actions-only checks of applied L1 methods and real ARM64 emitter output.
Host execution is fixture evidence, not an iPad or Steam performance result.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile

assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Run through GitHub Actions'
root = Path(__file__).resolve().parents[2]
patches = root / 'build/fex-patches'


def method(text, signature):
    start = text.index(signature)
    # These methods have preprocessor alternatives which each open a scope
    # (the Windows/non-Windows invalidation loop). Use their source indentation
    # for the method boundary, rather than counting both alternatives' braces.
    clean = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"',
                   lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]), text, flags=re.S)
    pos = clean.index('{', start)
    indent = re.match(r'[ \t]*', signature)[0]
    ending = re.search(r'(?m)^' + re.escape(indent) + r'\}', clean[pos+1:])
    assert ending, signature
    end = pos + 1 + ending.end()
    return text[start:end]


fixture = r'''
#include <algorithm>
#include <cassert>
#include <bit>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <optional>
#include <set>
#include <vector>
// Select the real PE policy after loading the host standard library.
#define FEX_IOS_HOST 1
#define _WIN32 1
#include <FEXCore/Utils/L1CacheIndex.h>
#define MDECK_STEAM_SCOPE(...) ((void)0)
#define FEXCORE_PROFILE_INSTANT_INCREMENT(...) ((void)0)
namespace LogMan::Msg { template<class... T> void EFmt(const char*,T...) {} }
namespace fextl { template<class T> using vector=std::vector<T>; }
namespace FEXCore {
inline unsigned ilog2(size_t value) { assert(std::has_single_bit(value));return std::countr_zero(value); }
namespace SHMStats { template<class T> struct AccumulationBlock { explicit AccumulationBlock(T*) {} }; }
namespace Allocator {
static unsigned clears;
inline void VirtualDontNeed(void* p,size_t n,bool) { assert(p&&n<=2*1024*1024);memset(p,0,n);++clears; }
}
namespace Core {
struct Stats { uint64_t AccumulatedCacheReadLockTime{},AccumulatedCacheWriteLockTime{}; };
struct Frame { struct { uint64_t L1Mask{}; } State; };
struct InternalThreadState { Stats* ThreadStats{};Frame* CurrentFrame{}; };
}
namespace CPU { struct CodeBuffer {}; }
struct LookupCacheBaseLockToken {};
struct LookupCacheWriteLockToken : LookupCacheBaseLockToken {};
struct GuestToHostMap {
  struct BlockEntry { uintptr_t HostCode;std::vector<uint64_t> CodePages;bool MDeckNormal; };
  std::map<uint64_t,BlockEntry> blocks;
  unsigned reads{};
  auto AcquireReadLock() { return LookupCacheBaseLockToken{}; }
  auto AcquireWriteLock() { return LookupCacheWriteLockToken{}; }
  BlockEntry* FindBlock(uint64_t a,const LookupCacheBaseLockToken&) {
    ++reads;auto it=blocks.find(a);return it==blocks.end()?nullptr:&it->second;
  }
  const BlockEntry& AddBlockMapping(uint64_t a,const std::vector<uint64_t>& pages,void* code,const LookupCacheWriteLockToken&,bool normal=false) {
    return blocks.insert_or_assign(a,BlockEntry{(uintptr_t)code,pages,normal}).first->second;
  }
  void ClearCache(const LookupCacheWriteLockToken&) { blocks.clear(); }
};
// Dependencies are controlled; all indexing, fill, invalidation, resizing and
// generation-change method bodies below are copied from the applied source.
struct CacheFixture {
  using LookupCache = CacheFixture;
  struct LookupCacheEntry { uintptr_t HostCode,GuestCode; };
  static constexpr size_t MIN_L1_ENTRIES=8192,MAX_L1_ENTRIES=131072;
  std::vector<LookupCacheEntry> storage=std::vector<LookupCacheEntry>(MAX_L1_ENTRIES);
  uintptr_t L1Pointer=(uintptr_t)storage.data(),L1PointerMask=MIN_L1_ENTRIES-1;
  uintptr_t AllocationBase=L1Pointer;size_t AllocationSize=MAX_L1_ENTRIES*16;
  const bool L1MixedIndex=MDeckL1::Enabled();
  uintptr_t PagePointer{},PageMemory{},VirtualMemSize=0x100000000ull;
  size_t CurrentL1Entries=MIN_L1_ENTRIES;
  uint64_t L2L3CacheHits{};
  std::chrono::time_point<std::chrono::system_clock> LastPeriod{};
  static constexpr std::chrono::seconds SamplePeriod{1};
  bool dynamic=true,l2=false;double increase=1e30,decrease=0;
  bool DynamicL1Cache() const { return dynamic; }
  bool DisableL2Cache() const { return !l2; }
  double DynamicL1CacheIncreaseCountHeuristic() const { return increase; }
  double DynamicL1CacheDecreaseCountHeuristic() const { return decrease; }
  std::map<uint64_t,std::set<uint64_t>> CachedCodePages;
  GuestToHostMap own;GuestToHostMap* Shared=&own;
  uintptr_t AllocateBackingForPage() { abort(); }
  void ClearL2Cache(const LookupCacheBaseLockToken&) { abort(); }
  @METHODS@
};
}
using namespace FEXCore;
static uint64_t random64(uint64_t& n) { n^=n<<13;n^=n>>7;n^=n<<17;return n; }
int main(int argc,char** argv) {
  const bool mixed=argc>1&&!strcmp(argv[1],"on");
  if(argc>1&&!strcmp(argv[1],"late")) {
    assert(!MDeckL1::Enabled());assert(!MDeckL1::Configure("1"));return 0;
  }
  if(argc>1&&!strcmp(argv[1],"invalid")) {
    assert(!MDeckL1::Configure("1junk"));assert(!MDeckL1::Configure("1"));return 0;
  }
  assert(MDeckL1::Configure(mixed?"1":"0")==mixed);
  assert(MDeckL1::Configure(mixed?"0":"1")==mixed); // immutable after selection
  CacheFixture c;Core::Frame frame;Core::InternalThreadState thread{nullptr,&frame};
  LookupCacheWriteLockToken lock;
  const auto add=[&](CacheFixture& cache,uint64_t a,uint64_t code) {
    cache.AddBlockMapping(&thread,a,{a&~0xfffull},(void*)code);
  };
  const auto find=[&](CacheFixture& cache,uint64_t a){return cache.FindBlock(&thread,a);};
  // Explicit 32-bit and high 64-bit guest aliases: full-address tags survive.
  const uint64_t a=0x6a001234,b=a+0x20000,wide=a+0x7200000000ull;
  add(c,a,0x120001000);add(c,b,0x120002000);add(c,wide,0x120003000);
  assert(find(c,a)==0x120001000&&find(c,b)==0x120002000&&find(c,wide)==0x120003000);
  const unsigned before=c.own.reads;
  assert(find(c,wide)==0x120003000&&c.own.reads==before);
  assert(!find(c,wide+0x100000000ull));
  // Constructed low-bit collisions: evidence for the mechanism, not Steam FPS.
  CacheFixture collision;
  for(unsigned i=0;i<8;i++)add(collision,a+i*0x20000,0x130001000+i*0x1000);
  for(unsigned pass=0;pass<100;pass++)for(unsigned i=0;i<8;i++)
    assert(find(collision,a+i*0x20000)==0x130001000+i*0x1000);
  assert(mixed?collision.own.reads==0:collision.own.reads==800);
  printf("collision fixture mode=%s slower-map-lookups=%u/800\n",mixed?"fold16-v1":"legacy",collision.own.reads);
  // Self-modifying code/page invalidation: authoritative block removed, all
  // per-thread cache entries invalidated, then replacement translation added.
  c.own.blocks.erase(a);assert(c.InvalidateCacheRange(a&~0xfffull,4096));
  assert(!find(c,a));add(c,a,0x140007000);assert(find(c,a)==0x140007000);
  // Dynamic growth must invalidate a block still stored at the smaller mask.
  CacheFixture grow;uint64_t guest=0x6a010000;
  while(grow.L1Index(guest,8191)==grow.L1Index(guest,16383))++guest;
  add(grow,guest,0x150001000);const auto oldIndex=grow.L1Index(guest,8191);
  grow.LastPeriod=std::chrono::system_clock::now()-std::chrono::seconds(2);
  grow.increase=1;grow.L2L3CacheHits=255;grow.UpdateDynamicL1Stats(&thread);
  assert(grow.CurrentL1Entries==16384&&frame.State.L1Mask==(16383u<<4));
  grow.InvalidateCache(guest,lock);assert(grow.storage[oldIndex].GuestCode==0);
  grow.own.blocks.erase(guest);assert(!find(grow,guest));
  // Shrink decommits upper entries; regrowth must not resurrect old code.
  add(grow,guest,0x150002000);grow.increase=1e30;grow.decrease=1e6;
  grow.LastPeriod=std::chrono::system_clock::now()-std::chrono::seconds(2);
  grow.L2L3CacheHits=255;grow.UpdateDynamicL1Stats(&thread);
  assert(grow.CurrentL1Entries==8192);
  grow.InvalidateCache(guest,lock);grow.own.blocks.erase(guest);
  grow.increase=1;grow.LastPeriod=std::chrono::system_clock::now()-std::chrono::seconds(2);
  grow.L2L3CacheHits=255;grow.UpdateDynamicL1Stats(&thread);assert(!find(grow,guest));
  // Buffer generation switch clears all L1 and page tracking before new map.
  GuestToHostMap newer;CPU::CodeBuffer previous;
  add(c,a,0x160001000);c.ChangeGuestToHostMapping(previous,newer,lock);
  assert(c.CachedCodePages.empty()&&!find(c,a));
  add(c,a,0x170001000);assert(find(c,a)==0x170001000);
  c.ClearCache(lock);assert(!find(c,a)&&newer.blocks.empty());
  // Populate from the actual full-L2 branch, then invalidate both levels.
  std::vector<uintptr_t> pageTable(1<<20);std::vector<CacheFixture::LookupCacheEntry> page(4096);
  CacheFixture full;full.l2=true;full.PagePointer=(uintptr_t)pageTable.data();
  pageTable[a>>12]=(uintptr_t)page.data();page[a&0xfff]={0x120009000,a};
  assert(find(full,a)==0x120009000&&full.storage[full.L1Index(a,full.L1PointerMask)].GuestCode==a);
  full.InvalidateCache(a,lock);assert(!find(full,a));
  // Random address/mask collisions always retain exact guest identity.
  CacheFixture randomCache;uint64_t rng=0x123456789abcdef;
  for(unsigned bits=13;bits<=17;bits++) {
    randomCache.ClearCache(lock);randomCache.L1PointerMask=(1ull<<bits)-1;
    for(unsigned i=0;i<20000;i++) {
      auto g=random64(rng)|0x10000;auto h=0x120000000ull+i*16;
      add(randomCache,g,h);assert(find(randomCache,g)==h);
      if(i%31==0){randomCache.own.blocks.erase(g);randomCache.InvalidateCache(g,lock);assert(!find(randomCache,g));}
    }
  }
  assert(Allocator::clears>0);
  puts("PASS applied C++ cache methods: identity, collisions, SMC/page invalidation, resize, buffer-generation reset, L2 refill, frozen policy");
}
'''

generator = r'''
#include <cassert>
#include <cstdio>
#include <FEXCore/Utils/L1CacheIndexEmitter.h>
namespace FEXCore::Assert { [[noreturn]] void ForcedAssert(){__builtin_trap();} }
int main() {
  using namespace ARMEmitter;
  for(bool mix:{false,true}) {
    alignas(16) uint32_t words[32]{};
    Emitter code((uint8_t*)words,sizeof(words));
    FEXCore::MDeckL1::EmitAddress(code,Reg::r1,Reg::r2,Reg::r0,Reg::r3,16,mix);
    size_t count=(code.GetCursorAddress<uintptr_t>()-(uintptr_t)words)/4;
    assert(count==(mix?6:3));
    printf(".text\n.p2align 2\n.globl _probe_%s\n_probe_%s:\nmsr nzcv, x5\n",mix?"mixed":"legacy",mix?"mixed":"legacy");
    for(size_t i=0;i<count;i++)printf(".long 0x%08x\n",words[i]);
    puts("mrs x7, nzcv\nstp x1,x7,[x6]\nstp x3,x4,[x6,#16]\nstr x0,[x6,#32]\nret");
  }
}
'''

runner = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <FEXCore/Utils/L1CacheIndex.h>
extern "C" void probe_legacy(const uint64_t*,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t*);
extern "C" void probe_mixed(const uint64_t*,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t*);
int main() {
  uint64_t rng=0x123456789abcdef;
  for(unsigned bits=13;bits<=17;bits++)for(unsigned i=0;i<10000;i++) {
    rng^=rng<<13;rng^=rng>>7;rng^=rng<<17;
    // Include 32-bit, high 64-bit and full-width inputs, at every NZCV value.
    uint64_t rip=i%3==0?(uint32_t)rng:i%3==1?(rng&0x7fffffffffull):rng;
    uint64_t frame[4]={0xdead,0xbeef,0x7020000000ull,((1ull<<bits)-1)<<4};
    for(bool mix:{false,true}) {
      uint64_t result[5]{};const uint64_t flags=(i%16ull)<<28;
      (mix?probe_mixed:probe_legacy)(frame,0,0,rip,0x1780000040ull,flags,result);
      assert(result[0]==frame[2]+16*FEXCore::MDeckL1::Index(rip,(1ull<<bits)-1,mix));
      assert(result[1]==flags&&result[2]==rip&&result[3]==0x1780000040ull&&result[4]==(uintptr_t)frame);
    }
  }
  puts("PASS real emitted ARM64 execution: all dynamic masks, 32/64-bit guest addresses, legacy/mixed, RIP/state/host-target/NZCV preserved");
}
'''

with tempfile.TemporaryDirectory(prefix='mdeck-l1-') as tmp:
    work=Path(tmp)
    names=set()
    for patch in patches.glob('*.patch'):
        names.update(re.findall(r'^--- a/(.+)$',patch.read_text(),re.M))
    subprocess.run(['git','init','-q',str(work)],check=True)
    for name in names:
        out=work/name;out.parent.mkdir(parents=True,exist_ok=True)
        out.write_bytes(subprocess.check_output(['git','-C',str(root/'FEX'),'show','HEAD:'+name]))
    for patch in sorted(patches.glob('*.patch')):
        subprocess.run(['git','-C',str(work),'apply','--check',str(patch)],check=True)
        subprocess.run(['git','-C',str(work),'apply',str(patch)],check=True)
    for patch in sorted(patches.glob('*.patch')):
        subprocess.run(['git','-C',str(work),'apply','--reverse','--check',str(patch)],check=True)
    deps=work/'include/FEXCore/Utils';deps.mkdir(parents=True)
    for name in ['L1CacheIndex.h','L1CacheIndexEmitter.h']:
        shutil.copyfile(patches/name,deps/name)
    h=(work/'FEXCore/Source/Interface/Core/LookupCache.h').read_text()
    cpp=(work/'FEXCore/Source/Interface/Core/LookupCache.cpp').read_text()
    selected=[method(h,s) for s in ['  uintptr_t FindBlock(', '  void UpdateDynamicL1Stats(',
        '  void AddBlockMapping(', '  void InvalidateCache(', '  bool InvalidateCacheRange(',
        '  void ChangeGuestToHostMapping(', '  uintptr_t GetScaledL1PointerMask(',
        '  size_t L1Index(', '  void CacheBlockMapping(']]
    selected += [method(cpp,s).replace('LookupCache::','') for s in
                 ['void LookupCache::ClearThreadLocalCaches(', 'void LookupCache::ClearCache(']]
    source=work/'lookup.cpp';source.write_text(fixture.replace('@METHODS@','\n'.join(selected)))
    base=['xcrun','clang++','-std=c++20','-O1','-g','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
          '-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(work/'include')]
    for mode in ['wow64','arm64ec']:
        binary=work/mode
        subprocess.run(base+(['-DARCHITECTURE_arm64ec'] if mode=='arm64ec' else [])+[str(source),'-o',str(binary)],check=True)
        for setting in ['on','off','late','invalid']:
            subprocess.run([str(binary),setting],check=True,timeout=30)
    # Negative control: leaving invalidation on the old index must fail.
    broken=source.read_text().replace('L1Index(Address, Entries - 1)','Address & (Entries - 1)')
    assert broken!=source.read_text()
    bad=work/'old-invalidation.cpp';bad.write_text(broken)
    subprocess.run(base+[str(bad),'-o',str(work/'bad')],check=True)
    result=subprocess.run([str(work/'bad'),'on'],capture_output=True,text=True,timeout=30)
    assert result.returncode!=0,'negative control failed to detect stale invalidation'
    print('PASS negative control: inconsistent invalidation is rejected')

    # Compile the actual emitter with only its logging/container dependencies
    # replaced. Opcodes and production EmitAddress are not mocked.
    (deps/'LogManager.h').write_text('#pragma once\n#include <cassert>\n#define LOGMAN_THROW_A_FMT(c,...) assert(c)\n#define LOGMAN_MSG_A_FMT(...) ((void)0)\n')
    vectors=work/'include/FEXCore/fextl';vectors.mkdir(parents=True)
    (vectors/'vector.h').write_text('#pragma once\n#include <vector>\nnamespace fextl { template<class T> using vector=std::vector<T>; }\n')
    g=work/'emit.cpp';g.write_text(generator)
    includes=['-I'+str(work/'include'),'-I'+str(root/'FEX/FEXCore/include'),
              '-I'+str(root/'FEX/FEXHeaderUtils'),'-I'+str(root/'FEX/CodeEmitter')]
    subprocess.run(['xcrun','clang++','-std=c++20','-O1','-DFEX_IOS_HOST',*includes,str(g),'-o',str(work/'emit')],check=True)
    assembly=work/'probe.S';assembly.write_bytes(subprocess.check_output([str(work/'emit')]))
    r=work/'run.cpp';r.write_text('#include <initializer_list>\n'+runner)
    subprocess.run(base+[str(r),str(assembly),'-o',str(work/'run')],check=True)
    subprocess.run([str(work/'run')],check=True,timeout=30)

    dispatcher=(work/'FEXCore/Source/Interface/Core/Dispatcher/Dispatcher.cpp').read_text()
    branch=(work/'FEXCore/Source/Interface/Core/JIT/BranchOps.cpp').read_text()
    assert dispatcher.count('MDeckL1::EmitAddress(')==3 and branch.count('MDeckL1::EmitAddress(')==1
    for source_text in [dispatcher,branch]:
        assert not re.search(r'and_\([^;]*ilog2\(sizeof\(LookupCache::LookupCacheEntry\)\)',source_text)
    assert not re.search(r'\[Address & (?:L1PointerMask|\(Entries - 1\))\]',h)
    assert 'const bool L1MixedIndex = MDeckL1::Enabled();' in h
    for mode in ['WOW64','ARM64EC']:
        module=(work/f'Source/Windows/{mode}/Module.cpp').read_text()
        assert module.index('MDeckL1::Configure(getenv("MADEIRA_FEX_L1_HASH"))')<module.index('CTX->InitCore();')
    print('PASS integration: four generated lookup/refill sites, C++ lookup/fill/invalidation and both PE initializers')

bridge=(root/'app/Madeira/WineProcessBridge.m').read_text()
assert bridge.index('unsetenv("MADEIRA_FEX_L1_HASH")') < bridge.index('setenv(k.UTF8String, v.UTF8String, 1);')
ui=(root/'app/Madeira/Library.swift').read_text()
toggle=ui.split('Toggle("Code cache lookup optimization (experimental)"',1)[1].split('Section("Diagnostics")',1)[0]
assert 'SteamCacheLookupSettings.text(file.text, enabled: enabled)' in toggle
assert '.disabled(model.current != nil || model.startingScreen)' in toggle
assert 'steam-cache-lookup-optimization' in toggle
print('PASS session/UI: clear stale env before profile export, persist selection, disable runtime edits')
print('UNRUN: complete PE build/link, real Wine concurrency, iPad Steam speed and stability acceptance')
