// mdeck-only compilation observations; default off and diagnostic-only.
#pragma once
#include "steam_compile_reason_abi.h"
namespace FEXCore::CompileReason {
#if defined(FEX_IOS_HOST) && defined(_WIN32)
extern "C" uint64_t mdeck_steam_probe_teb();
inline sr_bridge* Bridge {};
inline uint64_t Instance {}, BufferSerial {};
inline unsigned Path {};
inline uint64_t NextId() { return __atomic_fetch_add(&BufferSerial,1,__ATOMIC_RELAXED)+1; }
inline void Initialize(const char* text,unsigned path) {
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
  Path=path;Instance=id;__atomic_store_n(&Bridge,b,__ATOMIC_RELEASE);
  __atomic_fetch_or(&b->attached,path,__ATOMIC_RELAXED);
}
inline uint64_t Clock() { uint64_t ticks;__asm__ volatile("isb\nmrs %0, cntvct_el0":"=r"(ticks)::"memory");return ticks; }
class Capture {
  sr_bridge* bridge {};
  sr_ticket ticket {};
  sr_key key {};
  sr_fingerprint fingerprint=sr_fingerprint_init();
  uint64_t start {};
  unsigned fallback=SR_FAILED;
public:
  Capture(uint64_t owner,uint64_t rip,uint64_t max_inst,uint64_t mode,bool delivery) {
    bridge=__atomic_load_n(&Bridge,__ATOMIC_ACQUIRE);
    if(!bridge||!__atomic_load_n(&bridge->active_epoch,__ATOMIC_ACQUIRE))return;
    uint64_t teb=mdeck_steam_probe_teb();if(!teb)return;
    const auto* ids=reinterpret_cast<const uint64_t*>(teb+0x40);
    ticket=sr_begin(bridge,Instance,(unsigned)ids[0],(unsigned)ids[1],Path);
    key={ticket.instance,owner,rip,max_inst,mode};fallback=delivery?SR_DELIVERY:SR_FAILED;
    if(ticket.epoch)start=Clock();
  }
  bool Active() const { return ticket.epoch&&fallback!=SR_DELIVERY; }
  void Block(uint64_t address) {if(Active())sr_fingerprint_block(&fingerprint,address);}
  void Instruction(uint64_t address,const uint8_t* bytes,unsigned count) {if(Active())sr_fingerprint_inst(&fingerprint,address,bytes,count);}
  void Unsupported() {fingerprint.invalid=1;}
  void Finish(uint64_t generation,unsigned outcome) {
    if(!ticket.epoch)return;
    const uint64_t end=Clock();
    sr_finish(bridge,ticket,key,fingerprint,generation,fallback==SR_DELIVERY?SR_DELIVERY:outcome,end>=start?end-start:0);
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
  void Finish(uint64_t,unsigned){}
};
#endif
}
#if defined(FEX_IOS_HOST) && defined(_WIN32)
#define MDECK_COMPILE_CAPTURE(name,thread,rip,maxinst,mode,delivery) \
  FEXCore::CompileReason::Capture name((thread)->CPUBackend->GetCodeBufferManager().MDeckReasonOwner,rip,maxinst,mode,delivery)
#else
#define MDECK_COMPILE_CAPTURE(name,thread,rip,maxinst,mode,delivery) FEXCore::CompileReason::Capture name
#endif
