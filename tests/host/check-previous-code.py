#!/usr/bin/env python3
"""Actions-only: actual reuse methods with instrumented ownership/map adapters.
Does not emulate generated ARM64 or replace device/PE integration validation.
"""
from pathlib import Path
import os, re, subprocess, tempfile
assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Run only in GitHub Actions'
root = Path(__file__).resolve().parents[2]
patches = root / 'build/fex-patches'
def method(text, signature):
    start = text.index(signature); brace = text.index('{', start); depth = 1; end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}'); end += 1
    return text[start:end]
with tempfile.TemporaryDirectory(prefix='mdeck-previous-') as tmp:
    work = Path(tmp); source = work/'source'; source.mkdir()
    subprocess.run(['git','init','-q',str(source)],check=True)
    names = set()
    for p in patches.glob('*.patch'): names.update(re.findall(r'^--- a/(.+)$',p.read_text(),re.M))
    for name in names:
        target=source/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(subprocess.check_output(['git','-C',str(root/'FEX'),'show','HEAD:'+name]))
    for p in sorted(patches.glob('*.patch')):
        subprocess.run(['git','-C',str(source),'apply',str(p)],check=True)
    for p in sorted(patches.glob('*.patch')):
        subprocess.run(['git','-C',str(source),'apply','--reverse','--check',str(p)],check=True)
    backend=(source/'FEXCore/Source/Interface/Core/CPUBackend.cpp').read_text()
    lookup=(source/'FEXCore/Source/Interface/Core/LookupCache.h').read_text()
    core=(source/'FEXCore/Source/Interface/Core/Core.cpp').read_text()
    jit=(source/'FEXCore/Source/Interface/Core/JIT/JIT.cpp').read_text()
    methods='\n'.join(method(backend,s) for s in [
        'auto CodeBufferManager::GetReuseCandidates()', 'bool CodeBufferManager::IsReuseCandidate(',
        'void CodeBufferManager::StopPreviousReuse()', 'bool CPUBackend::IsInCurrentBuffer(',
        'uintptr_t CPUBackend::TryPreviousCode('])
    refill=method(lookup,'uintptr_t RefillPreviousBlock(')
    fixture=r'''
#include <cstddef>
#include <utility>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>
// Load the real host STL before selecting the tested PE policy branch.
#define FEX_IOS_HOST 1
#define _WIN32 1
#include "PreviousCode.h"
namespace fextl { template<class T> using shared_ptr=std::shared_ptr<T>; }
static int map_locks=0, destructions=0, resets=0;
static bool delivery=false, unpublished=false, valid_context=true;
static uint32_t shared_depth=1; // normal caller already holds global invalidation shared
static std::function<void()> migrate_hook, before_write_hook;
namespace FEXCore::Utils { struct WritePriorityMutex {
 static bool IosEmissionLocksHeldBySelf(){return delivery;}
 static bool IosUnpublishedCompileActive(){return unpublished;}
 struct IosReuseScopeState {uint32_t SharedDepth;bool BufferWriter,Unpublished,Valid;};
 static IosReuseScopeState IosGetReuseScopeState(){return {shared_depth,delivery,unpublished,valid_context};}
}; }
struct Token { bool write; explicit Token(bool w):write(w){assert(++map_locks==1);} ~Token(){--map_locks;} };
struct Entry { uintptr_t HostCode; std::vector<uint64_t> CodePages; bool MDeckNormal; };
struct Map {
 std::map<uint64_t,Entry> entries;
 Token AcquireReadLock(){return Token(false);} Token AcquireWriteLock(){
   if(before_write_hook){auto hook=std::move(before_write_hook);before_write_hook={};hook();}
   return Token(true);
 }
 const Entry* FindBlock(uint64_t rip,const Token&){auto it=entries.find(rip);return it==entries.end()?nullptr:&it->second;}
};
struct CodeBuffer {
 uintptr_t base; std::size_t AllocatedSize=4096; uint8_t* Ptr; std::unique_ptr<Map> LookupCache=std::make_unique<Map>();
 uint64_t MDeckReasonGeneration;
  explicit CodeBuffer(uintptr_t b):base(b),Ptr(reinterpret_cast<uint8_t*>(b)){
    static uint64_t serial=0;MDeckReasonGeneration=++serial;
  }
 ~CodeBuffer(){assert(map_locks==0);++destructions;}
 std::size_t UsableSize()const{return AllocatedSize;}
};
struct Lookup {
 Map* Shared; std::map<uint64_t,uintptr_t> local; std::vector<uint64_t> pages;
 void ChangeGuestToHostMapping(CodeBuffer& old,Map& next,const Token& t){
   assert(t.write && Shared==old.LookupCache.get()); local.clear();pages.clear();Shared=&next;
   if(migrate_hook){auto hook=std::move(migrate_hook);migrate_hook={};hook();}
 }
 void CacheBlockMapping(uint64_t rip,const Entry& e,bool,const Token&){local[rip]=e.HostCode;pages=e.CodePages;}
 REFILL_METHOD
};
struct Frame { unsigned SignalHandlerRefCounter=0; };
struct Thread { Frame* CurrentFrame; Lookup* LookupCache; };
namespace FEXCore::Core { static void ResetCallRetStack(Thread*,const char*){++resets;} }
struct IosMigrateLockGuard { std::mutex& mutex; explicit IosMigrateLockGuard(std::mutex& m):mutex(m){mutex.lock();} ~IosMigrateLockGuard(){mutex.unlock();} };
struct CodeBufferManager {
 using Ptr=fextl::shared_ptr<CodeBuffer>; struct ReuseCandidates {Ptr Latest,Previous;};
 std::mutex LatestMutex; Ptr Latest; FEXCore::MDeckPrevious::Slot<Ptr> PreviousSlot;
 std::atomic<uint64_t> ReuseDispatcherMisses{},ReuseAttempts{},ReuseLatestCandidates{},ReusePreviousCandidates{},
  ReuseLatestEntries{},ReusePreviousEntries{},ReuseRejectMaxInst{},ReuseRejectTF{},ReuseRejectDelivery{},ReuseRejectSignal{},
  ReuseRejectNoEntry{},ReuseRejectNonNormal{},ReuseRejectHostRange{},ReuseMigrationAttempts{},ReuseMigrationSwitches{},
  ReuseRefillAttempts{},ReuseRefillHits{},ReuseRefillMisses{},ReuseFallbackCompiles{},ReuseLatestHits{},ReusePreviousHits{},ReuseMisses{},ReuseEntryDelivery{},ReuseNormalReadScope{},ReuseRejectReadDepth{},ReuseRejectBufferWriter{},ReuseRejectUnpublished{},ReuseRejectUnknownContext{},ReuseRejectBacktrackBudget{},ReuseRejectCandidateChanged{};
 ReuseCandidates GetReuseCandidates();bool IsReuseCandidate(const Ptr&,const Ptr&);void StopPreviousReuse();void ReportPreviousReuse(){}
};
struct CPUBackend {
 Thread* ThreadState;CodeBufferManager& CodeBuffers;fextl::shared_ptr<CodeBuffer> CurrentCodeBuffer;
 mutable std::mutex IosMigrateLock;uint64_t PreviousBorrowedAtGeneration{};
 uintptr_t TryPreviousCode(uint64_t);bool IsInCurrentBuffer(uintptr_t)const;
 void RegisterForSignalHandler(const fextl::shared_ptr<CodeBuffer>&){assert(!ThreadState->CurrentFrame->SignalHandlerRefCounter);}
};
ACTUAL_METHODS
static auto buffer(uintptr_t base,uint64_t rip,bool normal=true){
 auto b=std::make_shared<CodeBuffer>(base);b->LookupCache->entries[rip]={base+128,{rip>>12,(rip>>12)+1},normal};return b;
}
int main(int argc,char** argv){
 assert(argc==2);std::string mode=argv[1];using namespace FEXCore::MDeckPrevious;
 if(mode=="default"){assert(!Enabled());assert(!Configure("1",true));return 0;}
 if(mode=="other"){assert(!Configure("1",false));assert(!Configure("1",true));return 0;}
 if(mode=="invalid"){assert(!Configure("1junk",true));return 0;}
 assert(Configure("1",true));assert(Enabled());assert(Configure("0",false));
 assert(NormalReadScope(true,1,false,false));
 assert(!NormalReadScope(true,0,false,false)&&!NormalReadScope(true,2,false,false));
 assert(!NormalReadScope(true,1,true,false)&&!NormalReadScope(true,1,false,true));
 assert(!NormalReadScope(false,1,false,false));
 // Actual retention policy: one slot, bounded, no forced execution-ref release.
 using Ptr=std::shared_ptr<CodeBuffer>;Slot<Ptr> slot;
 auto a=buffer(0x10000,0x4000),b=buffer(0x20000,0x8000),c=buffer(0x30000,0xc000);
 assert(!slot.Rotate({},true,false,0));assert(!slot.Stopped);
 assert(!slot.Rotate(a,true,true,4096));assert(slot.Previous==a);
 auto retired=slot.Rotate(b,true,true,4096);assert(retired==a && slot.Previous==b);retired.reset();
 retired=slot.Rotate(c,true,true,Slot<Ptr>::Budget+1);assert(retired==b && !slot.Previous);retired.reset();
 slot.Rotate(a,true,true,4096);retired=slot.Stop();assert(slot.Stopped && retired==a);retired.reset();
 slot.Rotate(b,true,true,4096);assert(!slot.Previous);
 Slot<Ptr> explicit_clear;explicit_clear.Rotate(a,true,false,4096);assert(explicit_clear.Stopped);
 Slot<Ptr> disabled;disabled.Rotate(a,false,true,4096);assert(!disabled.Previous);
 // Actual backend migration with strict single-map-lock and owner checks.
 CodeBufferManager manager;manager.Latest=b;manager.PreviousSlot.Previous=a;
 Lookup lookup{b->LookupCache.get(),{}, {}};Frame frame;Thread thread{&frame,&lookup};
 CPUBackend backend{&thread,manager,b,{}};
 lookup.local[123]=456;lookup.pages={999};
 assert(backend.TryPreviousCode(0x4000)==0x10080);
 assert(backend.CurrentCodeBuffer==a && lookup.Shared==a->LookupCache.get());
 assert(!lookup.local.count(123) && lookup.pages==std::vector<uint64_t>({4,5}) && resets==1);
 assert(backend.IsInCurrentBuffer(0x10080) && !backend.IsInCurrentBuffer(0x20080));
 assert(manager.ReusePreviousHits==1 && !b->LookupCache->entries.count(0x4000));
 assert(manager.ReuseLatestCandidates==1 && manager.ReusePreviousCandidates==1);
 assert(manager.ReusePreviousEntries==1 && manager.ReuseMigrationAttempts==1);
 assert(manager.ReuseMigrationSwitches==1 && manager.ReuseRefillAttempts==1 && manager.ReuseRefillHits==1);
 assert(manager.ReuseRefillMisses==0 && manager.ReuseFallbackCompiles==0);
 assert(backend.TryPreviousCode(0x8000)==0x20080 && manager.ReuseLatestHits==1);
  // Ordinary hot-code alternation must no longer migrate on every miss.
  const auto switches=manager.ReuseMigrationSwitches.load();const auto saved_resets=resets;
  for(unsigned i=0;i<10000;++i){
    assert(!backend.TryPreviousCode(0x4000)); // caller proceeds to ordinary compile on Latest
    assert(backend.CurrentCodeBuffer==b && lookup.Shared==b->LookupCache.get());
    assert(lookup.local.at(0x8000)==0x20080); // Latest hot block remains cached
  }
  assert(manager.ReuseMigrationSwitches==switches && resets==saved_resets);
  assert(manager.ReuseRejectBacktrackBudget==10000);
  // Erase/re-publish and a simulated forward compiler/sweeper migration do not
  // refund the once-per-generation token. A second thread has its own token.
  a->LookupCache->entries.erase(0x4000);
  a->LookupCache->entries[0x4000]={0x10090,{4,5},true};
  backend.CurrentCodeBuffer=b;assert(!backend.TryPreviousCode(0x4000));
  Lookup second_lookup{b->LookupCache.get(),{}, {}};Frame second_frame;Thread second_thread{&second_frame,&second_lookup};
  CPUBackend second{&second_thread,manager,b,{}};
  assert(second.TryPreviousCode(0x4000)==0x10090);
  // New Latest identity grants the first backend another backward migration.
  // Reuse the RX address to prove this is not an address-based quota.
  auto newer=buffer(b->base,0xc000);manager.Latest=newer;manager.PreviousSlot.Previous=b;
  backend.CurrentCodeBuffer=newer;lookup.Shared=newer->LookupCache.get();lookup.local.clear();lookup.pages.clear();
  assert(backend.TryPreviousCode(0x8000)==0x20080);
  assert(backend.PreviousBorrowedAtGeneration==newer->MDeckReasonGeneration);
  assert(backend.TryPreviousCode(0xc000)==newer->base+128);
  assert(!backend.TryPreviousCode(0x8000));
  // Independent backend exercises rejection paths before any quota is consumed.
  manager.Latest=b;manager.PreviousSlot.Previous=a;
  Lookup guard_lookup{b->LookupCache.get(),{}, {}};Frame guard_frame;Thread guard_thread{&guard_frame,&guard_lookup};
  CPUBackend guards{&guard_thread,manager,b,{}};
  auto no_entry=manager.ReuseRejectNoEntry.load();assert(!guards.TryPreviousCode(0x9000));
  assert(manager.ReuseRejectNoEntry>no_entry && !guards.PreviousBorrowedAtGeneration);
  a->LookupCache->entries[0x4000].HostCode=0xffff0000;
  assert(!guards.TryPreviousCode(0x4000) && manager.ReuseRejectHostRange>=1);
  a->LookupCache->entries[0x4000].HostCode=0x10080;
  a->LookupCache->entries[0x4000].MDeckNormal=false;assert(!guards.TryPreviousCode(0x4000));
  a->LookupCache->entries[0x4000].MDeckNormal=true;
  assert(manager.ReuseRejectNonNormal>=1 && !guards.PreviousBorrowedAtGeneration);
  auto attempts=manager.ReuseAttempts.load();guard_frame.SignalHandlerRefCounter=1;assert(!guards.TryPreviousCode(0x4000));
  assert(manager.ReuseRejectSignal>=1);
  guard_frame.SignalHandlerRefCounter=0;delivery=true;assert(!guards.TryPreviousCode(0x4000));delivery=false;
  assert(manager.ReuseRejectDelivery>=1);
  unpublished=true;assert(!guards.TryPreviousCode(0x4000));unpublished=false;assert(manager.ReuseAttempts==attempts);
  shared_depth=0;assert(!guards.TryPreviousCode(0x4000));
  shared_depth=2;assert(!guards.TryPreviousCode(0x4000));
  shared_depth=1;valid_context=false;assert(!guards.TryPreviousCode(0x4000));valid_context=true;
  assert(manager.ReuseAttempts==attempts&&manager.ReuseRejectReadDepth==2);
  assert(manager.ReuseRejectBufferWriter==1&&manager.ReuseRejectUnpublished==1&&manager.ReuseRejectUnknownContext==1);
  assert(manager.ReuseNormalReadScope==manager.ReuseAttempts);
  // Rotation after candidate inspection must reject the stale snapshot before
  // switching or consuming a token, even if that candidate is still retained.
  const auto before_rotation_switches=manager.ReuseMigrationSwitches.load();
  before_write_hook=[&]{manager.Latest=newer;};
  assert(!guards.TryPreviousCode(0x4000));
  assert(manager.ReuseRejectCandidateChanged>=1 && manager.ReuseMigrationSwitches==before_rotation_switches);
  assert(!guards.PreviousBorrowedAtGeneration && guards.CurrentCodeBuffer==b);
  manager.Latest=b;
  // Concurrent entry replacement after switching fails refill but consumes the
  // token. Re-publishing that entry cannot cause another backward migration.
  migrate_hook=[&]{a->LookupCache->entries[0x4000].MDeckNormal=false;};
  assert(!guards.TryPreviousCode(0x4000) && !guard_lookup.local.count(0x4000));
  assert(guards.PreviousBorrowedAtGeneration==b->MDeckReasonGeneration);
  assert(guards.TryPreviousCode(0x8000)==0x20080);
  a->LookupCache->entries.erase(0x4000);assert(!guards.TryPreviousCode(0x4000));
  a->LookupCache->entries[0x4000]={0x10090,{4,5},true};assert(!guards.TryPreviousCode(0x4000));
  // Lifetime: an active backend still pins the old buffer after explicit stop.
  // Remove this fixture's separate slot reference before checking final release.
  slot.Stop();
  std::weak_ptr<CodeBuffer> old=a;manager.StopPreviousReuse();a.reset();
  assert(!old.expired()); // second is still executing Previous
  assert(!second.TryPreviousCode(0x8000));
  second.CurrentCodeBuffer=b;assert(old.expired());
 assert(map_locks==0 && destructions>0);
}
'''.replace('REFILL_METHOD',refill).replace('ACTUAL_METHODS',methods)
    cpp=work/'reuse.cpp';cpp.write_text(fixture)
    exe=work/'reuse'
    subprocess.run(['xcrun','clang++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(patches),str(cpp),'-o',str(exe)],check=True)
    for mode in ['default','other','invalid','on']:subprocess.run([str(exe),mode],check=True)
    native=work/'native.cpp';native.write_text('#include "PreviousCode.h"\n#include <cassert>\nint main(){FEXCore::MDeckPrevious::Configure("1",true);assert(!FEXCore::MDeckPrevious::Enabled());}\n')
    subprocess.run(['xcrun','clang++','-std=c++20','-Wall','-Wextra','-Werror','-I'+str(patches),str(native),'-o',str(work/'native')],check=True)
    subprocess.run([str(work/'native')],check=True)
    # Integration contracts not exercised by host adapters.
    compile_block=core[core.index('uintptr_t ContextImpl::CompileBlock('):core.index('uintptr_t ContextImpl::CompileSingleStep(')]
    assert 'FromDispatcher && FEXCore::MDeckPrevious::Enabled()' in compile_block
    assert 'ReuseDispatcherMisses.fetch_add' in compile_block
    assert 'ReuseRejectMaxInst.fetch_add' in compile_block
    assert 'ReuseRejectTF.fetch_add' in compile_block
    assert 'ReuseFallbackCompiles.fetch_add' in compile_block
    assert '!Frame->State.flags[X86State::RFLAG_TF_RAW_LOC]' in compile_block
    assert compile_block.index('IosEmissionLocksHeldBySelf()')<compile_block.index('CodeInvalidationMutex')
    assert 'IosEmissionLocksHeldBySelf()' not in method(backend,'uintptr_t CPUBackend::TryPreviousCode(')
    assert 'ReuseEntryDelivery.fetch_add' in compile_block
    assert compile_block.index('CodeInvalidationMutex')<compile_block.index('TryPreviousCode(GuestRIP)')<compile_block.index('auto [CompiledCode, DebugData, StartAddr, Length, NeedsAddGuestCodeRanges]')
    assert 'MaxInst == 0 && NeedsAddGuestCodeRanges && !Frame->State.flags[X86State::RFLAG_TF_RAW_LOC]' in compile_block
    dispatcher=(source/'FEXCore/Source/Interface/Core/Dispatcher/Dispatcher.cpp').read_text()
    assert 'PMFCompileBlock(&FEXCore::Context::ContextImpl::CompileBlockFromDispatcher)' in dispatcher
    linker=jit[jit.index('uint64_t Arm64JITCore::ExitFunctionLink('):jit.index('uint64_t Arm64JITCore::ExitFunctionLink(')+15000]
    assert linker.index('MDeckPrevious::Enabled()')<linker.index('->CompileBlock(')
    for check in ['IsInCurrentBuffer(reinterpret_cast<uintptr_t>(Record))','IsInCurrentBuffer(HostCode)']:assert check in linker
    assert linker.index('IsInCurrentBuffer(HostCode)')<linker.index('AddBlockLink(')
    alloc=method(backend,'auto CodeBufferManager::AllocateNew(')
    assert alloc.index('std::move(PreviousSlot.Previous)')<alloc.index('make_shared<CodeBuffer>')
    assert 'MDeckReasonRequestBytes != 0' in alloc
    assert 'Buffer->MDeckReasonGeneration = FEXCore::CompileReason::NextId();' in alloc
    reuse=method(backend,'uintptr_t CPUBackend::TryPreviousCode(')
    assert 'IsReuseCandidate(Candidate, Candidates.Latest)' in reuse
    assert reuse.index('PreviousBorrowedAtGeneration = Generation')<reuse.index('CurrentCodeBuffer = Candidate')<reuse.index('RefillPreviousBlock')
    assert backend.count('PreviousBorrowedAtGeneration =')==1
    backend_header=(source/'FEXCore/Source/Interface/Core/CPUBackend.h').read_text()
    assert 'uint64_t PreviousBorrowedAtGeneration {};' in backend_header
    assert 'StopPreviousReuse()' in method(core,'void ContextImpl::ClearCodeCache(')
    # Existing invalidation traverses every live buffer, retained ones included.
    assert 'InvalidateRange' in method(core,'void ContextImpl::InvalidateCodeBuffersCodeRange(')
    for path in ['WOW64','ARM64EC']:
        text=(source/f'Source/Windows/{path}/Module.cpp').read_text()
        assert text.index('MDeckPrevious::Configure(')<text.index('if (const char* ReasonBridge')<text.index('CTX->InitCore();')
        assert '"MADEIRA_FEX_PREVIOUS_CODE"), CEF && !Segments)' in text
bridge=(root/'app/Madeira/WineProcessBridge.m').read_text()
assert bridge.index('unsetenv("MADEIRA_FEX_PREVIOUS_CODE")')<bridge.index('setenv(k.UTF8String, v.UTF8String, 1);')
print('PASS previous-slot lifetime, bounded backtracking/rotation/failed-refill, actual migration/refill adapters, mode guards and patch-chain contracts')
print('UNRUN: ARM64 execution/linking, concurrent Windows SMC/unmap/exception integration, real-device safety and speed')
