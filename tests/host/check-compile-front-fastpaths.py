#!/usr/bin/env python3
"""Actions-only: differential checks for actual compile-front-end fast paths."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import tarfile

assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Run this check in GitHub Actions'
root = Path(__file__).resolve().parents[2]
patches = root / 'build/fex-patches'
# The runtime check checkout initializes FEX, but not its nested dependencies.
# Fetch exactly the pinned header implementation used by the production set.
subprocess.run(['git','-C',str(root/'FEX'),'submodule','update','--init','--depth','1',
                'External/unordered_dense'],check=True)
ra_path = 'FEXCore/Source/Interface/IR/Passes/RegisterAllocationPass.cpp'
front_path = 'FEXCore/Source/Interface/Core/Frontend.h'
op_path = 'FEXCore/Source/Interface/Core/OpcodeDispatcher.cpp'

def body(text, signature):
    begin = text.index('{', text.index(signature))
    depth = 1
    end = begin + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[begin:end]

fixture = r'''
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <random>
#include <set>
#include <utility>
#include <vector>
#include <ankerl/unordered_dense.h>
static size_t allocations=0;
template<class T> struct CounterAlloc {
 using value_type=T;
 CounterAlloc()=default;
 template<class U> CounterAlloc(const CounterAlloc<U>&){}
 T* allocate(size_t n){++allocations;return std::allocator<T>{}.allocate(n);}
 void deallocate(T* p,size_t n){std::allocator<T>{}.deallocate(p,n);}
 template<class U> bool operator==(const CounterAlloc<U>&)const{return true;}
};
namespace fextl {template<class K>using robin_set=ankerl::unordered_dense::set<K,std::hash<K>,std::equal_to<K>,CounterAlloc<K>>;}
// ACTUAL_VISITED_CLASS
static void check_visited(){
 VisitedSet now;std::set<uint64_t> old;std::mt19937_64 rng(0x51004);
 for(unsigned i=0;i<60000;i++){
  const auto key=(rng()%8192)*0x100000001ULL;
  if(i%379==0){now.clear();old.clear();}
  if(i%3){assert(now.insert(key).second==old.insert(key).second);}
  assert(now.contains(key)==old.contains(key));assert(now.size()==old.size());
 }
 now.clear();
 for(uint64_t i=0;i<2048;i++)now.emplace(i*0x100000001ULL);
 const auto warm=allocations;
 for(unsigned round=0;round<100;round++){
  now.clear();assert(now.empty());
  for(uint64_t i=0;i<2048;i++)assert(now.emplace(i*0x100000001ULL).second);
  for(uint64_t i=0;i<2048;i++)assert(now.contains(i*0x100000001ULL));
 }
 assert(allocations==warm);
 now.clear();for(uint64_t i=0;i<40000;i++)now.insert(i);
 assert(now.bucket_count()>VisitedSet::MaxRetainedBuckets);
 now.clear();assert(now.empty()&&now.bucket_count()<=VisitedSet::MaxRetainedBuckets);
 VisitedSet other;other.insert(UINT64_MAX);now.insert(0);
 assert(!now.contains(UINT64_MAX)&&!other.contains(0));
 try{now.insert(0x123456789abcdef0ULL);throw 1;}catch(int){}
 now.clear();assert(!now.contains(0x123456789abcdef0ULL));
}
// Lightweight IR adapters: execute the full real before/after merge bodies,
// with observable helper calls and rewrites. Not execution of guest IR.
enum OpCode {OP_OTHER,OP_MOV,OP_PUSH,OP_POP,OP_DIV,OP_UDIV,OP_XGETBV,OP_CPUID,OP_CONSTANT};
enum class OpSize {i16Bit=2,i32Bit=4,i64Bit=8};
struct Ref {
 int Index=0;bool Immediate=false;
 bool IsInvalid()const{return Index<0;}
 void SetInvalid(){Index=-1;}
 bool IsImmediate()const{return Immediate;}
 void SetImmediate(int x){Index=x;Immediate=true;}
 bool operator==(const Ref&)const=default;
};
struct Reg {int Raw;bool IsInvalid()const{return Raw<0;}bool operator==(const Reg&)const=default;};
struct IROp_Header {
 OpCode Op=OP_OTHER;OpSize Size=OpSize::i32Bit,ValueSize=OpSize::i32Bit;
 std::array<Ref,4> Args{{{2},{3},{4},{5}}};
 Ref Upper{2},Lower{3},OutRemainder{4},OutEAX{4},OutEBX{5},OutECX{6},OutEDX{7};
 uint64_t Constant=0;
 template<class T>T* C(){return static_cast<T*>(this);}
 template<class T>T* CW(){return static_cast<T*>(this);}
 bool operator==(const IROp_Header&)const=default;
};
using IROp_Push=IROp_Header;using IROp_Constant=IROp_Header;
namespace IR {using IROp_Div=IROp_Header;using IROp_XGetBV=IROp_Header;using IROp_CPUID=IROp_Header;
 enum class FenceType{Inst};inline int GetRAArgs(OpCode){return 4;}}
namespace CPUIDEmu {struct SupportsConstant {
 enum {CONSTANT,VARIABLE};enum class NeedsLeafConstant {NEEDSLEAFCONSTANT,NOLEAF};
 int SupportsConstantFunction;NeedsLeafConstant NeedsLeaf;
};}
struct FakeCPU {
 bool Constant=true,Leaf=false;
 struct Result{unsigned eax=11,ebx=12,ecx=13,edx=14;};
 bool DoesXCRFunctionReportConstantData(uint64_t)const{return Constant;}
 Result RunXCRFunction(uint64_t){return {};}
 CPUIDEmu::SupportsConstant DoesFunctionReportConstantData(uint64_t)const{
  return {Constant?CPUIDEmu::SupportsConstant::CONSTANT:CPUIDEmu::SupportsConstant::VARIABLE,
          Leaf?CPUIDEmu::SupportsConstant::NeedsLeafConstant::NEEDSLEAFCONSTANT:CPUIDEmu::SupportsConstant::NeedsLeafConstant::NOLEAF};}
 Result RunFunction(uint64_t,uint64_t){return {};}
};
enum {SR_SCAN_RA_MERGE_TRUE,SR_SCAN_RA_MERGE_REWRITE_FALSE,SR_SCAN_RA_MERGE_REG_MISMATCH,SR_SCAN_RA_MERGE_MOVE_INELIGIBLE};
struct TimingScope {bool Enabled=true;std::array<unsigned,4> Counts{};
 bool Active()const{return Enabled;}void Work(unsigned k){if(Enabled)++Counts[k];}};
struct FakeIR {std::array<IROp_Header,8> Ops{};unsigned Reads=0;
 template<class T>T* GetOp(Ref r){++Reads;return static_cast<T*>(&Ops.at(r.Index));}};
struct Emitter {
 struct ConstantNode{int Reg=0;};std::vector<ConstantNode> Constants;std::vector<int> Trace;
 Emitter(){Constants.reserve(8);}
 void SetWriteCursorBefore(Ref r){Trace.push_back(100+r.Index);}
 void RemovePostRA(Ref r){Trace.push_back(200+r.Index);}
 void _PushTwo(OpSize s,OpSize v,Ref a,Ref b,Ref c){Trace.insert(Trace.end(),{300,int(s),int(v),a.Index,b.Index,c.Index});}
 void _PopTwo(OpSize s,Ref a,Ref b,Ref c){Trace.insert(Trace.end(),{400,int(s),a.Index,b.Index,c.Index});}
 void _Fence(IR::FenceType){Trace.push_back(500);}
 struct Pair{ConstantNode* Node;};
 Pair _Constant(unsigned v){Trace.push_back(600+int(v));Constants.push_back({});return {&Constants.back()};}
};
#define LOGMAN_THROW_A_FMT(c,...) assert(c)
struct MergeHarness {
 FakeIR* IR;Emitter* IREmit;FakeCPU* CPUID;std::array<int,8> Registers{};
 bool SignExtend=false,MoveEligible=false;unsigned KillCalls=0;
 Reg PhysicalRegister(Ref r)const{return {r.IsInvalid()?-1:r.Immediate?r.Index:Registers.at(r.Index)};}
 bool IsSignext(IROp_Header*,Ref,OpSize)const{return SignExtend;}
 bool IsZero(IROp_Header* h)const{return h->Op==OP_CONSTANT&&h->Constant==0;}
 bool KillMove(IROp_Header*,IROp_Header*,Ref,Ref){++KillCalls;return MoveEligible;}
 bool Before(Ref LastNode,Ref CodeNode,IROp_Header* IROp,TimingScope& Timing) // BEFORE_MERGE
 bool After(Ref LastNode,Ref CodeNode,IROp_Header* IROp,TimingScope& Timing) // AFTER_MERGE
};
static void check_merge(){
 std::mt19937 rng(973);
 unsigned skips=0,true_special=0,false_rewrites=0;
 for(unsigned i=0;i<30000;i++){
  FakeIR a;Emitter ea,eb;FakeCPU ca;ca.Constant=i%3!=0;ca.Leaf=i%5==0;
  for(auto& op:a.Ops){op.Op=OpCode(rng()%9);op.Size=OpSize(2u<<(rng()%3));op.ValueSize=OpSize(2u<<(rng()%3));op.Constant=rng()%2;}
  // Enumerate all current opcodes, including every excluded special branch.
  a.Ops[1].Op=OpCode(i%9);
  MergeHarness x{&a,&ea,&ca};for(auto& r:x.Registers)r=int(rng()%4);
  x.SignExtend=i%2;x.MoveEligible=i%3==0;
  FakeIR b=a;FakeCPU cb=ca;MergeHarness y=x;y.IR=&b;y.IREmit=&eb;y.CPUID=&cb;
  TimingScope ta,tb;ta.Enabled=tb.Enabled=i%2==0;
  bool ra=x.Before({0},{1},&a.Ops[1],ta),rb=y.After({0},{1},&b.Ops[1],tb);
  assert(ra==rb&&a.Ops==b.Ops&&ea.Trace==eb.Trace&&ta.Counts==tb.Counts&&x.KillCalls==y.KillCalls);
  assert(ea.Constants.size()==eb.Constants.size());
  for(size_t j=0;j<ea.Constants.size();j++)assert(ea.Constants[j].Reg==eb.Constants[j].Reg);
  assert(b.Reads<=a.Reads);
  if(b.Reads<a.Reads)++skips;
  if(ra&&i%9>=OP_PUSH&&i%9<=OP_CPUID)++true_special;
  if(!ra&&!ea.Trace.empty())++false_rewrites;
 }
 assert(skips>0&&true_special>0&&false_rewrites>0);
}
struct JumpInfo{int BlockEntry;};
struct JumpMap:std::map<uint64_t,JumpInfo>{unsigned Finds=0;auto find(uint64_t k){++Finds;return std::map<uint64_t,JumpInfo>::find(k);}};
struct JumpHarness {
 JumpMap JumpTargets;std::vector<int64_t> Trace;
 int GetNewJumpBlock(uint64_t rip){auto i=JumpTargets.find(rip);assert(i!=JumpTargets.end());return i->second.BlockEntry;}
 void Jump(int v){Trace.push_back(v);}int Jump(){Trace.push_back(-1);return 10;}
 int GetCurrentBlock(){return 20;}int CreateNewCodeBlockAfter(int n){Trace.push_back(n);return 30;}
 void SetJumpTarget(int a,int b){Trace.push_back(a+b);}void SetCurrentCodeBlock(int n){Trace.push_back(n);}
 void StartNewBlock(){Trace.push_back(40);}void ExitRelocatedPC(int,int64_t off){Trace.push_back(off);}
 void Before(bool Multiblock,uint64_t TargetRIP,int64_t TargetOffset){int Op=0; // BEFORE_JUMP
 }
 void After(bool Multiblock,uint64_t TargetRIP,int64_t TargetOffset){int Op=0; // AFTER_JUMP
 }
};
static void check_jump(){
 for(bool multi:{false,true})for(bool present:{false,true})for(uint64_t rip:{uint64_t(0),uint64_t(0xffffffff),UINT64_MAX}){
  JumpHarness a,b;if(present){a.JumpTargets.emplace(rip,JumpInfo{41});b.JumpTargets.emplace(rip,JumpInfo{41});}
  a.Before(multi,rip,-123);b.After(multi,rip,-123);assert(a.Trace==b.Trace);
  assert(a.JumpTargets.Finds==(multi?(present?2u:1u):0u));assert(b.JumpTargets.Finds==(multi?1u:0u));
 }
}
int main(){check_visited();check_merge();check_jump();}
'''

with tempfile.TemporaryDirectory(prefix='mdeck-front-fast-') as tmp:
    work = Path(tmp)
    source = work / 'source'
    source.mkdir()
    archive = work / 'pin.tar'
    with archive.open('wb') as out:
        subprocess.run(['git', '-C', str(root/'FEX'), 'archive', 'HEAD'], stdout=out, check=True)
    with tarfile.open(archive) as packed:
        packed.extractall(source)
    before = None
    for patch in sorted(patches.glob('*.patch')):
        if patch.name.startswith('0008-'):
            before = {p: (source/p).read_text() for p in (ra_path,front_path,op_path)}
        subprocess.run(['git','-C',str(source),'apply','--check',str(patch)],check=True)
        subprocess.run(['git','-C',str(source),'apply',str(patch)],check=True)
    assert before is not None
    for patch in sorted(patches.glob('*.patch')):
        subprocess.run(['git','-C',str(source),'apply','--reverse','--check',str(patch)],check=True)
    after = {p: (source/p).read_text() for p in before}
    old_body = body(before[ra_path], 'bool ConstrainedRAPass::TryPostRAMerge(')
    new_body = body(after[ra_path], 'bool ConstrainedRAPass::TryPostRAMerge(')
    # The complete existing special/ordinary paths must be byte-identical.
    suffix = old_body[old_body.index('  auto LastOp'):]
    assert new_body.endswith(suffix)
    special = new_body[:new_body.index('  auto LastOp')]
    special_opcodes = set(re.findall(r'IROp->Op == (OP_[A-Z0-9_]+)',old_body.split('// Merge moves')[0]))
    assert special_opcodes == {'OP_PUSH','OP_POP','OP_DIV','OP_UDIV','OP_XGETBV','OP_CPUID'}
    for opcode in special_opcodes:
        assert f'case {opcode}:' in special
    visited = 'class VisitedSet '+body(after[front_path], 'class VisitedSet :')+';'
    # Keep the actual base class, which body() deliberately omits.
    visited = visited.replace('class VisitedSet {', 'class VisitedSet : public fextl::robin_set<uint64_t> {', 1)
    for ordered in ['CurrentBlockTargets', 'BlocksToDecode']:
        assert f'fextl::set<uint64_t> {ordered};' in after[front_path]
    frontend=(source/'FEXCore/Source/Interface/Core/Frontend.cpp').read_text()
    assert 'BlocksToDecode.merge(CurrentBlockTargets);' in frontend
    for forbidden in ['VisitedBlocks.begin(', 'VisitedBlocks.end(', 'VisitedBlocks.lower_bound(']:
        assert forbidden not in frontend
    assert after[op_path] == before[op_path].replace('Jump(GetNewJumpBlock(TargetRIP));','Jump(JumpBlock->second.BlockEntry);')
    start=before[op_path].index('  if (Multiblock) {',before[op_path].index('// This is just an unconditional relative literal jump'))
    end=before[op_path].index('\n}\n',start)
    old_jump=before[op_path][start:end]
    new_jump=old_jump.replace('Jump(GetNewJumpBlock(TargetRIP));','Jump(JumpBlock->second.BlockEntry);')
    generated=fixture.replace('// ACTUAL_VISITED_CLASS',visited).replace('// BEFORE_MERGE',old_body).replace('// AFTER_MERGE',new_body).replace('// BEFORE_JUMP',old_jump).replace('// AFTER_JUMP',new_jump)
    cpp=work/'differential.cpp';cpp.write_text(generated)
    for level in ['-O0','-O2']:
        exe=work/('differential'+level)
        subprocess.run(['xcrun','clang++','-std=c++20',level,'-g','-Wall','-Wextra','-Werror',
                        '-fsanitize=address,undefined','-fno-omit-frame-pointer',
                        '-I'+str(root/'FEX/External/unordered_dense/include'),str(cpp),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
print('PASS actual RA merge before/after with special rewrites; visited membership/retained allocations/bound; direct jump lookup equivalence; full patch chain')
print('UNRUN: guest IR execution, full PE compile/link, device correctness and performance; helper adapters are not a complete IR runtime')
