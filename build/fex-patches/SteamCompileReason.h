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
  unsigned fallback=SR_FAILED;
public:
  Capture(uint64_t owner,uint64_t rip,uint64_t max_inst,uint64_t mode,bool delivery) {
    bridge=__atomic_load_n(&Bridge,__ATOMIC_ACQUIRE);
    if(!bridge||!__atomic_load_n(&bridge->active_epoch,__ATOMIC_ACQUIRE))return;
    uint64_t teb=mdeck_steam_probe_teb();if(!teb)return;
    const auto* ids=reinterpret_cast<const uint64_t*>(teb+0x40);
    ticket=sr_begin(bridge,Instance,(unsigned)ids[0],(unsigned)ids[1],Path);ticket.cef=CEF;
    key={ticket.instance,owner,rip,max_inst,mode};fallback=delivery?SR_DELIVERY:SR_FAILED;
    if(ticket.epoch)start=last=Clock();
  }
  bool Active() const { return ticket.epoch&&fallback!=SR_DELIVERY; }
  void Block(uint64_t address) {if(Active())sr_fingerprint_block(&fingerprint,address);}
  void Instruction(uint64_t address,const uint8_t* bytes,unsigned count) {if(Active())sr_fingerprint_inst(&fingerprint,address,bytes,count);}
  void Unsupported() {fingerprint.invalid=1;}
  void Stage(unsigned next) {
    if(!Active()||next>=SR_STAGES)return;
    const auto now=Clock();if(now>=last)timing.ticks[stage]+=now-last;last=now;stage=next;
  }
  void Output(sr_output value) {output=value;}
  void Finish(uint64_t generation,unsigned outcome) {
    if(!ticket.epoch)return;
    const uint64_t end=Clock();
    if(end>=last)timing.ticks[stage]+=end-last;
    sr_finish_detail(bridge,ticket,key,fingerprint,generation,fallback==SR_DELIVERY?SR_DELIVERY:outcome,
                     end>=start?end-start:0,&timing,output);
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
   void Output(sr_output){}
  void Finish(uint64_t,unsigned){}
};
#endif
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
