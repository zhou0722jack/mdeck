// mdeck-only compilation observations; default off and diagnostic-only.
#pragma once
#include "steam_compile_reason_abi.h"
namespace FEXCore::CompileReason {
// Counted UTF-16 basename, read once from the initializing process's own PEB.
inline bool IsCEFImage(const uint16_t* text,unsigned bytes) {
  if(!text||bytes%2||bytes>32766)return false;
  const unsigned count=bytes/2;unsigned base=0;
  for(unsigned i=0;i<count;i++)if(text[i]=='/'||text[i]=='\\')base=i+1;
  constexpr char expected[]="steamwebhelper.exe";
  if(count-base!=sizeof(expected)-1)return false;
  for(unsigned i=0;i<sizeof(expected)-1;i++) {
    unsigned c=text[base+i];if(c>='A'&&c<='Z')c+='a'-'A';
    if(c!=(unsigned)expected[i])return false;
  }
  return true;
}
// Caller already owns CodeBufferWriteMutex. Restore on nested calls and exits.
class CapacityScope {
  uint64_t* slot;uint64_t previous;
public:
  CapacityScope(uint64_t* slot,uint64_t requested):slot(slot),previous(slot?*slot:0){if(slot)*slot=requested;}
  ~CapacityScope(){if(slot)*slot=previous;}
  CapacityScope(const CapacityScope&)=delete;
  CapacityScope& operator=(const CapacityScope&)=delete;
};
#if defined(FEX_IOS_HOST) && defined(_WIN32)
extern "C" uint64_t mdeck_steam_probe_teb();
inline sr_bridge* Bridge {};
inline uint64_t Instance {}, BufferSerial {};
inline unsigned Path {};
inline bool CEF {};
inline uint64_t NextId() { return __atomic_fetch_add(&BufferSerial,1,__ATOMIC_RELAXED)+1; }
inline void Initialize(const char* text,unsigned path,bool cef=false) {
  uintptr_t address=0;
  if(!text||!*text)return;
  unsigned digits=0;
  for(;*text;++text) {
    unsigned d=*text>='0'&&*text<='9'?*text-'0':*text>='a'&&*text<='f'?*text-'a'+10:16;
    if(d==16||++digits>sizeof(address)*2||address>(UINTPTR_MAX-d)/16)return;
    address=address*16+d;
  }
  if(address<0x100000000ull||address%alignof(sr_bridge))return;
  auto* b=reinterpret_cast<sr_bridge*>(address);
  if(b->magic!=SR_MAGIC||b->bytes!=sizeof(sr_bridge)||!b->frequency)return;
  const auto id=__atomic_fetch_add(&b->next_instance,1,__ATOMIC_RELAXED)+1;
  Path=path;CEF=cef;Instance=id;__atomic_store_n(&Bridge,b,__ATOMIC_RELEASE);
  __atomic_fetch_or(&b->attached,path,__ATOMIC_RELAXED);
}
inline uint64_t Clock() { uint64_t ticks;__asm__ volatile("isb\nmrs %0, cntvct_el0":"=r"(ticks)::"memory");return ticks; }
inline void BufferAllocated(uint64_t owner,uint64_t previous,uint64_t old_rx,uint64_t old_used,uint64_t old_capacity,
                            uint64_t generation,uint64_t rx,uint64_t capacity,uint64_t requested) {
  auto* b=__atomic_load_n(&Bridge,__ATOMIC_ACQUIRE);if(!b)return;
  sr_buffer_event e {};e.epoch=__atomic_load_n(&b->active_epoch,__ATOMIC_ACQUIRE);if(!e.epoch)return;
  e.instance=Instance;e.owner=owner;e.ticks=Clock();e.path=Path;
  // This is an ordering marker, not necessarily the triggering compile ticket.
  e.order=__atomic_load_n(&b->begun,__ATOMIC_RELAXED);
  if(const auto teb=mdeck_steam_probe_teb()) {
    const auto* ids=reinterpret_cast<const uint64_t*>(teb+0x40);e.pid=(unsigned)ids[0];e.tid=(unsigned)ids[1];
  }
  e.previous=previous;e.generation=generation;e.old_rx=old_rx;e.old_used=old_used;e.old_capacity=old_capacity;
  e.rx=rx;e.capacity=capacity;e.requested=requested;
  e.reason=!previous?SR_BUFFER_INITIAL:requested?SR_BUFFER_CAPACITY:SR_BUFFER_EXPLICIT;
  sr_buffer_record(b,e);
}
class Capture {
  sr_bridge* bridge {};
  sr_ticket ticket {};
  sr_key key {};
  sr_fingerprint fingerprint=sr_fingerprint_init();
  uint64_t start {},last {};
  unsigned stage=SR_OTHER;
  sr_timing timing {};
  sr_output output {};
  sr_frontend frontend; // Initialized only for an enrolled diagnostic call.
  uint64_t ir_last {};
  unsigned ir_phase=SR_IR_OTHER;
  void CloseIRPhase(uint64_t now) {
    if(now>=ir_last)sr_add(&frontend.phases[ir_phase],now-ir_last);
    ir_last=now;
  }
  unsigned fallback=SR_FAILED;
public:
  Capture(uint64_t owner,uint64_t rip,uint64_t max_inst,uint64_t mode,bool delivery) {
    bridge=__atomic_load_n(&Bridge,__ATOMIC_ACQUIRE);
    if(!bridge||!__atomic_load_n(&bridge->active_epoch,__ATOMIC_ACQUIRE))return;
    uint64_t teb=mdeck_steam_probe_teb();if(!teb)return;
    const auto* ids=reinterpret_cast<const uint64_t*>(teb+0x40);
    ticket=sr_begin(bridge,Instance,(unsigned)ids[0],(unsigned)ids[1],Path);ticket.cef=CEF;
    key={ticket.instance,owner,rip,max_inst,mode};fallback=delivery?SR_DELIVERY:SR_FAILED;
    if(ticket.epoch){frontend={};start=last=Clock();}
  }
  bool Active() const { return ticket.epoch&&fallback!=SR_DELIVERY; }
  void Block(uint64_t address) {if(Active())sr_fingerprint_block(&fingerprint,address);}
  void Instruction(uint64_t address,const uint8_t* bytes,unsigned count) {if(Active())sr_fingerprint_inst(&fingerprint,address,bytes,count);}
  void Unsupported() {fingerprint.invalid=1;}
  void Stage(unsigned next) {
    if(!Active()||next>=SR_STAGES)return;
    const auto now=Clock();
    if(stage==SR_DECODE_IR)CloseIRPhase(now);
    if(now>=last)timing.ticks[stage]+=now-last;
    last=now;stage=next;
    if(next==SR_DECODE_IR){frontend.calls++;ir_last=now;ir_phase=SR_IR_OTHER;}
  }
  void IRStage(unsigned next) {
    if(!Active()||stage!=SR_DECODE_IR||next>=SR_IR_PHASES||next==ir_phase)return;
    CloseIRPhase(Clock());ir_phase=next;
  }
  void Decoded(uint64_t instructions,uint64_t blocks) {
    if(!Active())return;
    sr_work_add(&frontend.decoded_instructions,instructions);sr_work_add(&frontend.decoded_blocks,blocks);
  }
  void Emitted(uint64_t instructions,uint64_t slots,bool custom) {
    if(!Active())return;
    sr_work_add(&frontend.emitted_instructions,instructions);sr_work_add(&frontend.ssa_before,slots);
    frontend.custom+=custom;
  }
  void IRReturned(uint64_t slots) {
    if(!Active())return;
    frontend.returned++;sr_work_add(&frontend.ssa_after,slots);
  }
  uint64_t PassBegin(unsigned pass,uint64_t slots) {
    if(!Active()||stage!=SR_DECODE_IR)return 0;
    if(pass>=SR_IR_PASSES_COUNT)pass=SR_PASS_OTHER;
    sr_work_add(&frontend.pass_ssa_in[pass],slots);return Clock();
  }
  void PassEnd(unsigned pass,uint64_t begin,bool completed,uint64_t slots) {
    if(!begin)return;
    const auto end=Clock();if(pass>=SR_IR_PASSES_COUNT)pass=SR_PASS_OTHER;
    if(end>=begin)sr_add(&frontend.passes[pass],end-begin);
    if(completed)sr_work_add(&frontend.pass_ssa_out[pass],slots);
  }
  uint64_t RABegin(uint64_t& sequence) {
    if(!Active()||stage!=SR_DECODE_IR)return 0;
    frontend.ra.eligible++;
    return (sequence++ % SR_RA_STRIDE)==0 ? Clock() : 0;
  }
  static uint64_t RAClock(){return Clock();}
  void RAEnd(const sr_ra_sample& sample) {
    auto& ra=frontend.ra;ra.sampled++;ra.returned+=sample.returned;
    sr_add(&ra.total,sample.total);
    for(unsigned i=0;i<SR_RA_PHASES;i++)sr_add(&ra.phases[i],sample.ticks[i]);
    sr_work_add(&ra.slots,sample.slots);sr_work_add(&ra.blocks,sample.blocks);
    sr_work_add(&ra.reverse_nodes,sample.reverse_nodes);sr_work_add(&ra.forward_nodes,sample.forward_nodes);
    sr_work_add(&ra.suspect_blocks,sample.suspect_blocks);
  }
  void Output(sr_output value) {output=value;}
  void Finish(uint64_t generation,unsigned outcome) {
    if(!ticket.epoch)return;
    const uint64_t end=Clock();
    if(stage==SR_DECODE_IR)CloseIRPhase(end);
    if(end>=last)timing.ticks[stage]+=end-last;
    sr_finish_full(bridge,ticket,key,fingerprint,generation,fallback==SR_DELIVERY?SR_DELIVERY:outcome,
                     end>=start?end-start:0,&timing,output,&frontend);
    ticket.epoch=0;
  }
  ~Capture(){Finish(0,fallback);}
  Capture(const Capture&)=delete;
  Capture& operator=(const Capture&)=delete;
};
#else
inline constexpr uint64_t NextId(){return 0;}
class Capture {
public:
  bool Active() const {return false;}
  void Block(uint64_t){}
  void Instruction(uint64_t,const uint8_t*,unsigned){}
  void Unsupported(){}
   void Stage(unsigned){}
   void IRStage(unsigned){}
   void Decoded(uint64_t,uint64_t){}
   void Emitted(uint64_t,uint64_t,bool){}
   void IRReturned(uint64_t){}
   uint64_t PassBegin(unsigned,uint64_t){return 0;}
   void PassEnd(unsigned,uint64_t,bool,uint64_t){}
   uint64_t RABegin(uint64_t&){return 0;}
   static uint64_t RAClock(){return 0;}
   void RAEnd(const sr_ra_sample&){}
   void Output(sr_output){}
  void Finish(uint64_t,unsigned){}
};
#endif
// Sample entire RA invocations. All phase boundaries share one clock reading;
// no clock reads per node and no additional IR walk. Total is nested in RA pass.
class RAScope {
  Capture* capture;uint64_t begin,last;unsigned phase=SR_RA_SETUP;
  sr_ra_sample sample; // untouched on unsampled/default-off calls
  void Close(uint64_t now) {if(now>=last)sample.ticks[phase]+=now-last;last=now;}
public:
  RAScope(Capture* capture,uint64_t& sequence):capture(capture),
    begin(capture?capture->RABegin(sequence):0),last(begin){if(begin)sample={};}
  bool Active() const {return begin!=0;}
  void Stage(unsigned next){if(!begin||next>=SR_RA_PHASES||phase==next)return;Close(Capture::RAClock());phase=next;}
  void Slots(uint64_t n){if(begin)sample.slots=n;}
  void Block(){if(begin)sample.blocks++;}
  void ReverseNode(){if(begin)sample.reverse_nodes++;}
  void ForwardNode(){if(begin)sample.forward_nodes++;}
  void SuspectBlock(){if(begin)sample.suspect_blocks++;}
  void Complete(){if(begin)sample.returned=1;}
  ~RAScope(){if(begin){const auto end=Capture::RAClock();Close(end);sample.total=end>=begin?end-begin:0;capture->RAEnd(sample);}}
  RAScope(const RAScope&)=delete;
  RAScope& operator=(const RAScope&)=delete;
};
// Stack-owned; no TLS or global current-capture pointer. Unwinding still records
// an entered pass, with no output workload sample when Run did not return.
class PassScope {
  Capture* capture;unsigned pass;uint64_t begin;
public:
  PassScope(Capture* capture,unsigned pass,uint64_t slots):capture(capture),pass(pass),
    begin(capture?capture->PassBegin(pass,slots):0){}
  void Complete(uint64_t slots){if(capture)capture->PassEnd(pass,begin,true,slots);begin=0;}
  ~PassScope(){if(capture)capture->PassEnd(pass,begin,false,0);}
  PassScope(const PassScope&)=delete;
  PassScope& operator=(const PassScope&)=delete;
};
}
#if defined(FEX_IOS_HOST) && defined(_WIN32)
#define MDECK_COMPILE_CAPTURE(name,thread,rip,maxinst,mode,delivery) \
  FEXCore::CompileReason::Capture name((thread)->CPUBackend->GetCodeBufferManager().MDeckReasonOwner,rip,maxinst,mode,delivery)
#define MDECK_REASON_GENERATION(code) ((code).MDeckReasonGeneration)
#define MDECK_REASON_OUTPUT(code) ((code).MDeckReasonOutput)
#define MDECK_REASON_CAPACITY(name,manager,size) FEXCore::CompileReason::CapacityScope name(&(manager).MDeckReasonRequestBytes,size)
#else
#define MDECK_COMPILE_CAPTURE(name,thread,rip,maxinst,mode,delivery) FEXCore::CompileReason::Capture name
#define MDECK_REASON_GENERATION(code) 0
#define MDECK_REASON_OUTPUT(code) sr_output{}
#define MDECK_REASON_CAPACITY(name,manager,size) FEXCore::CompileReason::CapacityScope name(nullptr,0)
#endif
