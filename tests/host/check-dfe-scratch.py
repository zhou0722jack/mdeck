#!/usr/bin/env python3
"""Actions-only: actual DFE CFG before/after and reusable scratch lifetime tests."""
from pathlib import Path
import os
import json
import subprocess
import tempfile

assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Run this check in GitHub Actions'
root = Path(__file__).resolve().parents[2]
patches = root / 'build/fex-patches'
dfe = 'FEXCore/Source/Interface/IR/Passes/RedundantFlagCalculationElimination.cpp'
ra = 'FEXCore/Source/Interface/IR/Passes/RegisterAllocationPass.cpp'

fixture = r'''
#include <cassert>
#include <cstdint>
#include <deque>
#include <vector>
#include <stdexcept>
#include <cstdio>
#include "DFEScratch.h"
static size_t allocations[4]{};
template<class T, int Tag> struct CountingAllocator {
  using value_type=T;
  template<class U> struct rebind {using other=CountingAllocator<U,Tag>;};
  CountingAllocator()=default;
  template<class U> CountingAllocator(const CountingAllocator<U,Tag>&){}
  T* allocate(size_t n){++allocations[Tag];return std::allocator<T>{}.allocate(n);}
  void deallocate(T* p,size_t n){std::allocator<T>{}.deallocate(p,n);}
  template<class U> bool operator==(const CountingAllocator<U,Tag>&) const {return true;}
};
namespace fextl {
  template<class T> using vector=std::vector<T,CountingAllocator<T,0>>;
  template<class T> using deque=std::deque<T>;
}
namespace LogMan::Msg {template<class... A> void EFmt(const char*, A&&...) {}}
using Ref=void*;
struct IROp_CodeBlock {uint32_t ID;};
namespace IR {using IROp_CodeBlock=::IROp_CodeBlock;}
struct OrderedNodeWrapper {size_t Index;};
struct Header {uint64_t OriginalRIP=0x10000;};
struct IRListView {
  Header H;
  std::vector<IROp_CodeBlock> Nodes;
  Header* GetHeader(){return &H;}
  template<class T> T* GetOp(OrderedNodeWrapper n){return &Nodes.at(n.Index);}
};
#define FLAG_ALL 63
namespace legacy {
// LEGACY_CFG
}
namespace optimized {
// OPTIMIZED_CFG
}
using Blocks=std::vector<optimized::BlockInfo,CountingAllocator<optimized::BlockInfo,1>>;
using Seen=std::vector<uint8_t,CountingAllocator<uint8_t,2>>;
using Scratch=FEXCore::IR::DFEScratch<Blocks,Seen,std::deque<uint32_t,CountingAllocator<uint32_t,3>>>;
// Production CFG uses fextl::vector<BlockInfo>&, so keep that exact type here.
using CFGScratch=FEXCore::IR::DFEScratch<fextl::vector<optimized::BlockInfo>,Seen,std::deque<uint32_t>>;

static void compare_cfg(CFGScratch& owner,unsigned count,bool reuse) {
  CFGScratch::Lease lease(owner,reuse);auto& data=lease.Get();
  IRListView ir;for(unsigned i=0;i<count;i++)ir.Nodes.push_back({i});
  legacy::ControlFlowGraph old{.IR=ir};std::deque<uint32_t> old_queue;
  optimized::ControlFlowGraph now{.BlockMap=data.BlockMap,.IR=ir,.Reuse=reuse};
  old.Init(old_queue,count);now.Init(data.Worklist,count);
  if(!reuse)for(unsigned i=0;i<count;i++)
    assert(now.Get(i)->Predecessors.capacity()==old.Get(i)->Predecessors.capacity());
  // Diamond joins, duplicate edges and a cycle. Insertion order must survive reuse.
  for(unsigned i=0;i<count;i++) {
    auto ptr=reinterpret_cast<void*>(uintptr_t(i+1));old.Get(i)->Node=ptr;now.Get(i)->Node=ptr;
    for(unsigned j=0;j<3;j++) {
      OrderedNodeWrapper to{(i+j+1)%count};old.RecordEdge(i,to);now.RecordEdge(i,to);
    }
  }
  assert(now.PredecessorDigest()==old.PredecessorDigest());
  for(unsigned i=0;i<count;i++)assert(now.Get(i)->Predecessors==old.Get(i)->Predecessors);
  assert(now.Get(count)==&now.Sentinel&&old.Get(count)==&old.Sentinel);
  assert(now.Sentinel.Flags==FLAG_ALL&&now.Sentinel.InWorklist);
  now.AddWorklist(data.Worklist,count);old.AddWorklist(old_queue,count);
  // Exercise actual push_front/pop_back paths and repeated predecessor scheduling.
  unsigned steps=0;
  while(!old_queue.empty()) {
    assert(data.Worklist==old_queue);const auto id=old_queue.back();
    old.Get(id)->InWorklist=false;now.Get(id)->InWorklist=false;
    if(steps++<count*2)for(auto pred:old.Get(id)->Predecessors) {
      old.AddWorklist(old_queue,pred);now.AddWorklist(data.Worklist,pred);
    }
    old_queue.pop_back();data.Worklist.pop_back();
  }
  assert(data.Worklist.empty()&&old.BadIDs==now.BadIDs);
}
static void fill(Scratch::Storage& data,unsigned count) {
  assert(data.Worklist.empty()&&data.SeenIDs.empty());
  data.BlockMap.resize(count);data.SeenIDs.assign(count,0);
  for(unsigned i=0;i<count;i++) {
    auto& b=data.BlockMap[i];assert(b.Predecessors.empty()&&!b.Node&&!b.Flags&&!b.InWorklist);
    b.Node=reinterpret_cast<void*>(uintptr_t(i+1));b.Flags=FLAG_ALL;b.InWorklist=true;
    b.Predecessors.push_back(i);b.Predecessors.push_back((i+1)%count);
    data.Worklist.push_back(i);
  }
}
int main(int argc,char** argv) {
  using namespace FEXCore::MDeckDFE;
  assert(Parse(nullptr)&&Parse("")&&Parse("1")&&Parse("false")&&Parse("00")&&!Parse("0"));
  const bool early=argc>1&&argv[1][0]=='e';
  const bool expected=early||argc<2||Parse(argv[1]);
  if(early)assert(Enabled());
  assert(Configure(early?"0":(argc>1?argv[1]:nullptr))==expected);
  assert(Enabled()==expected);
  assert(Configure(expected?"0":"1")==expected); // immutable for the PE lifetime
  const auto idle_allocations=allocations[3];
  Scratch fresh;
  assert(allocations[3]==idle_allocations); // no unused cached deque in off mode
  for(unsigned i=0;i<3;i++) {
    const auto old_blocks=allocations[1],old_seen=allocations[2],old_pred=allocations[0];
    {Scratch::Lease off(fresh,false);
     assert(off.Get().BlockMap.capacity()==0&&off.Get().SeenIDs.capacity()==0);
     fill(off.Get(),8);}
    assert(allocations[1]>old_blocks&&allocations[2]>old_seen&&allocations[0]>old_pred);
  }
  try {Scratch::Lease off(fresh,false);fill(off.Get(),8);throw 1;}catch(int){}
  {Scratch::Lease next(fresh,false);assert(next.Get().BlockMap.empty());}

  CFGScratch cfg;
  {CFGScratch::Lease lease(cfg);IRListView ir;
   optimized::ControlFlowGraph empty{.BlockMap=lease.Get().BlockMap,.IR=ir};
   empty.Init(lease.Get().Worklist,8);
   for(const auto& block:empty.BlockMap)assert(block.Predecessors.capacity()==0);
  }
  for(bool reuse:{false,true})for(unsigned count:{32u,4u,64u,1u,32u})compare_cfg(cfg,count,reuse);
  Scratch owner;
  {Scratch::Lease lease(owner);fill(lease.Get(),32);}
  const size_t pred=allocations[0],blocks=allocations[1],seen=allocations[2];
  for(unsigned i=0;i<1000;i++){Scratch::Lease lease(owner);fill(lease.Get(),32);}
  // No repeated block, predecessor or Seen allocations for a warmed same-size CFG.
  assert(allocations[0]==pred&&allocations[1]==blocks&&allocations[2]==seen);
  {Scratch::Lease outer(owner);fill(outer.Get(),32);
   {Scratch::Lease nested(owner);assert(nested.Get().BlockMap.empty());fill(nested.Get(),3);}
   assert(outer.Get().BlockMap[0].Node&&outer.Get().Worklist.size()==32);
   Scratch independent;{Scratch::Lease other(independent);assert(other.Get().BlockMap.empty());}
  }
  try {Scratch::Lease lease(owner);fill(lease.Get(),32);throw std::runtime_error("unwind");}
  catch(const std::runtime_error&){}
  {Scratch::Lease lease(owner);fill(lease.Get(),32);} // verifies old pointers/flags/queue were cleared
  {Scratch::Lease lease(owner);fill(lease.Get(),Scratch::MaxRetainedBlocks+1);}
  {Scratch::Lease lease(owner);assert(lease.Get().BlockMap.capacity()==0);assert(lease.Get().SeenIDs.capacity()==0);}
  {Scratch::Lease lease(owner);fill(lease.Get(),1);
   lease.Get().BlockMap[0].Predecessors.reserve(Scratch::MaxRetainedPredecessors+1);}
  {Scratch::Lease lease(owner);assert(lease.Get().BlockMap.capacity()==0);fill(lease.Get(),1);}
  puts("PASS actual DFE CFG order/digest/sentinel equivalence; scratch allocation reuse, nesting, unwind and retention bounds");
}
'''

with tempfile.TemporaryDirectory(prefix='mdeck-dfe-') as tmp:
    work=Path(tmp)
    subprocess.run(['git','init','-q',str(work)],check=True)
    originals={}
    for name in [dfe,ra]:
        text=subprocess.check_output(['git','-C',str(root/'FEX'),'show','HEAD:'+name],text=True)
        originals[name]=text
        dest=work/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text)
    subprocess.run(['git','-C',str(work),'apply',str(patches/'0006-dfe-scratch-ra-sampling.patch')],check=True)
    updated=(work/dfe).read_text()
    assert 'const bool ReuseScratch = FEXCore::MDeckDFE::Enabled();' in updated
    assert 'Scratch::Lease Lease {ScratchData, ReuseScratch};' in updated
    assert '.Reuse = ReuseScratch' in updated

    # The full analysis/rewriting functions and all propagation/recovery guards
    # must remain byte-for-byte unchanged; only scratch initialization is altered.
    start='unsigned DeadFlagCalculationEliminination::FlagsForCondClassType'
    end='void DeadFlagCalculationEliminination::Run('
    assert originals[dfe].split(start,1)[1].split(end,1)[0]==updated.split(start,1)[1].split(end,1)[0]
    before=originals[dfe].split('  // Gather CFG',1)[1]
    after=updated.split('  // Gather CFG',1)[1]
    after=after.replace('      fextl::vector<uint8_t> LocalSeen;\n      auto& Seen = ReuseScratch ? Storage.SeenIDs : LocalSeen;\n      Seen.assign(CFG.BlockMap.size(), 0);',
                        '      fextl::vector<uint8_t> Seen(CFG.BlockMap.size(), 0);')
    assert before==after,'DFE propagation/validation/rewriting changed'
    def cfg(text):
        return 'struct BlockInfo'+text.split('struct BlockInfo',1)[1].split('class DeadFlagCalculationEliminination',1)[0]
    text=fixture.replace('// LEGACY_CFG',cfg(originals[dfe])).replace('// OPTIMIZED_CFG',cfg(updated))
    source=work/'fixture.cpp';source.write_text(text)
    binary=work/'fixture'
    subprocess.run(['xcrun','clang++','-std=c++20','-O1','-g','-Wall','-Wextra','-Werror',
                    '-Wno-missing-field-initializers','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                    '-I'+str(patches),str(source),'-o',str(binary)],check=True)
    for args in [[],['0'],['1'],['early']]:
        subprocess.run([str(binary),*args],check=True,timeout=45)
bridge=(root/'app/Madeira/WineProcessBridge.m').read_text()
assert bridge.index('unsetenv("MADEIRA_FEX_DFE_REUSE")')<bridge.index('setenv(k.UTF8String, v.UTF8String, 1);')
ui=(root/'app/Madeira/Library.swift').read_text()
toggle=ui[ui.index('Toggle("DFE temporary storage reuse"'):ui.index('.accessibilityIdentifier("steam-dfe-scratch-reuse")')]
assert 'SteamDFEScratchSettings.text(file.text, enabled: enabled)' in toggle
assert '.disabled(model.current != nil || model.startingScreen)' in toggle
assert 'SteamCompileReasonSettings' not in toggle and 'SteamCacheLookupSettings' not in toggle
catalog=json.loads((root/'app/Madeira/Localizable.xcstrings').read_text())
assert catalog['strings']['DFE temporary storage reuse']['localizations']['zh-Hans']['stringUnit']['value']=='DFE 临时存储复用'
print('UNRUN: full FEX compilation and device performance; fixture does not execute guest IR')
