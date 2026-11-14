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
#include "PreviousCode.h"
#include <atomic>
#include <cassert>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>
namespace fextl { template<class T> using shared_ptr=std::shared_ptr<T>; }
static int map_locks=0, destructions=0, resets=0;
static bool delivery=false, unpublished=false;
static std::function<void()> migrate_hook;
namespace FEXCore::Utils { struct WritePriorityMutex {
 static bool IosEmissionLocksHeldBySelf(){return delivery;}
 static bool IosUnpublishedCompileActive(){return unpublished;}
}; }
struct Token { bool write; explicit Token(bool w):write(w){assert(++map_locks==1);} ~Token(){--map_locks;} };
struct Entry { uintptr_t HostCode; std::vector<uint64_t> CodePages; bool MDeckNormal; };
struct Map {
 std::map<uint64_t,Entry> entries;
 Token AcquireReadLock(){return Token(false);} Token AcquireWriteLock(){return Token(true);}
 const Entry* FindBlock(uint64_t rip,const Token&){auto it=entries.find(rip);return it==entries.end()?nullptr:&it->second;}
};
struct CodeBuffer {
 uintptr_t base; std::size_t AllocatedSize=4096; uint8_t* Ptr; std::unique_ptr<Map> LookupCache=std::make_unique<Map>();
 explicit CodeBuffer(uintptr_t b):base(b),Ptr(reinterpret_cast<uint8_t*>(b)){}
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
 std::atomic<uint64_t> ReuseAttempts{},ReuseLatestHits{},ReusePreviousHits{},ReuseMisses{};
 ReuseCandidates GetReuseCandidates();bool IsReuseCandidate(const Ptr&);void StopPreviousReuse();void ReportPreviousReuse(){}
};
struct CPUBackend {
 Thread* ThreadState;CodeBufferManager& CodeBuffers;fextl::shared_ptr<CodeBuffer> CurrentCodeBuffer;
 mutable std::mutex IosMigrateLock;
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
 assert(backend.TryPreviousCode(0x8000)==0x20080 && manager.ReuseLatestHits==1);
 assert(backend.TryPreviousCode(0x9000)==0);
 a->LookupCache->entries[0x4000].MDeckNormal=false;assert(backend.TryPreviousCode(0x4000)==0);
 a->LookupCache->entries[0x4000].MDeckNormal=true;
 auto attempts=manager.ReuseAttempts.load();frame.SignalHandlerRefCounter=1;assert(!backend.TryPreviousCode(0x4000));
 frame.SignalHandlerRefCounter=0;delivery=true;assert(!backend.TryPreviousCode(0x4000));delivery=false;
 unpublished=true;assert(!backend.TryPreviousCode(0x4000));unpublished=false;assert(manager.ReuseAttempts==attempts);
 // Simulate concurrent publication between candidate inspection and refill.
 migrate_hook=[&]{a->LookupCache->entries[0x4000].MDeckNormal=false;};
 assert(!backend.TryPreviousCode(0x4000) && !lookup.local.count(0x4000));
 assert(backend.TryPreviousCode(0x8000)==0x20080);a->LookupCache->entries.erase(0x4000);
 assert(!backend.TryPreviousCode(0x4000)); // invalidated/unmapped entry cannot be resurrected
 a->LookupCache->entries[0x4000]={0x10090,{4,5},true};assert(backend.TryPreviousCode(0x4000)==0x10090);
 std::weak_ptr<CodeBuffer> old=a;manager.StopPreviousReuse();a.reset();
 assert(!old.expired()); // active execution owner pins it after removing search entry
 assert(!backend.TryPreviousCode(0x8000)); // explicit stop fails closed
 backend.CurrentCodeBuffer=b;assert(old.expired());
 assert(map_locks==0 && destructions>0);
}
'''.replace('REFILL_METHOD',refill).replace('ACTUAL_METHODS',methods)
    cpp=work/'reuse.cpp';cpp.write_text(fixture)
    exe=work/'reuse'
    subprocess.run(['xcrun','clang++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-DFEX_IOS_HOST','-D_WIN32','-I'+str(patches),str(cpp),'-o',str(exe)],check=True)
    for mode in ['default','other','invalid','on']:subprocess.run([str(exe),mode],check=True)
    native=work/'native.cpp';native.write_text('#include "PreviousCode.h"\n#include <cassert>\nint main(){FEXCore::MDeckPrevious::Configure("1",true);assert(!FEXCore::MDeckPrevious::Enabled());}\n')
    subprocess.run(['xcrun','clang++','-std=c++20','-Wall','-Wextra','-Werror','-I'+str(patches),str(native),'-o',str(work/'native')],check=True)
    subprocess.run([str(work/'native')],check=True)
    # Integration contracts not exercised by host adapters.
    compile_block=core[core.index('uintptr_t ContextImpl::CompileBlock('):core.index('uintptr_t ContextImpl::CompileSingleStep(')]
    assert 'FromDispatcher && !IosUnpublished && MaxInst == 0' in compile_block
    assert '!Frame->State.flags[X86State::RFLAG_TF_RAW_LOC]' in compile_block
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
    assert 'StopPreviousReuse()' in method(core,'void ContextImpl::ClearCodeCache(')
    # Existing invalidation traverses every live buffer, retained ones included.
    assert 'InvalidateRange' in method(core,'void ContextImpl::InvalidateCodeBuffersCodeRange(')
    for path in ['WOW64','ARM64EC']:
        text=(source/f'Source/Windows/{path}/Module.cpp').read_text()
        assert text.index('MDeckPrevious::Configure(')<text.index('if (const char* ReasonBridge')<text.index('CTX->InitCore();')
        assert '"MADEIRA_FEX_PREVIOUS_CODE"), CEF)' in text
bridge=(root/'app/Madeira/WineProcessBridge.m').read_text()
assert bridge.index('unsetenv("MADEIRA_FEX_PREVIOUS_CODE")')<bridge.index('setenv(k.UTF8String, v.UTF8String, 1);')
print('PASS previous-slot budget/lifetime, actual migration/refill methods with adapters, mode guards and full patch-chain contracts')
print('UNRUN: ARM64 execution/linking, concurrent Windows SMC/unmap/exception integration, real-device safety and speed')
