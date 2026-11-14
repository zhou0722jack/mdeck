// mdeck diagnostic hooks, installed only in the local iOS FEX build.
#pragma once
#include "steam_probe_abi.h"
#if defined(FEX_IOS_HOST) && defined(_WIN32)
extern "C" uint64_t mdeck_steam_probe_teb();
namespace FEXCore::SteamProbe {
inline sf_bridge* Bridge {};
inline void Initialize(const char* text, unsigned path) {
  // The app publishes its permanent host allocation after applying user env.
  // Only parse that private ABI; no CRT numeric parser or TLS initialization.
  uintptr_t address = 0;
  if (!text || !*text) return;
  unsigned digits = 0;
  for (; *text; ++text) {
    unsigned d = *text >= '0' && *text <= '9' ? *text - '0' :
                 *text >= 'a' && *text <= 'f' ? *text - 'a' + 10 : 16;
    if (d == 16 || ++digits > sizeof(address) * 2 || address > (UINTPTR_MAX - d) / 16) return;
    address = address * 16 + d;
  }
  if (address < 0x100000000ull || address % alignof(sf_bridge)) return;
  auto* b = reinterpret_cast<sf_bridge*>(address);
  if (b->magic != SF_MAGIC || b->bytes != sizeof(sf_bridge) || !b->frequency) return;
  __atomic_store_n(&Bridge, b, __ATOMIC_RELEASE);
  __atomic_fetch_or(&b->attached, path, __ATOMIC_RELAXED);
}
inline uint64_t Clock() {
  uint64_t ticks;
  // Same architectural counter domain as the host's CNTFRQ_EL0 frequency.
  __asm__ volatile("isb\nmrs %0, cntvct_el0" : "=r"(ticks) :: "memory");
  return ticks;
}
class Scope {
  sf_bridge* bridge {};
  sf_ticket ticket {};
  uint64_t start {};
public:
  explicit Scope(unsigned stage) {
    bridge = __atomic_load_n(&Bridge, __ATOMIC_ACQUIRE);
    if (!bridge || !__atomic_load_n(&bridge->active_epoch, __ATOMIC_ACQUIRE)) return;
    const uint64_t teb = mdeck_steam_probe_teb();
    if (!teb) return;
    // Native TEB ClientId.UniqueThread: reject a recycled TEB with a new TID.
    const auto tid = *reinterpret_cast<const uint64_t*>(teb + 0x48);
    ticket = sf_enter(bridge, teb, static_cast<unsigned>(tid), stage);
    if (ticket.slot) start = Clock();
  }
  ~Scope() { if (ticket.slot) sf_leave(bridge, ticket, start, Clock()); }
  Scope(const Scope&) = delete;
  Scope& operator=(const Scope&) = delete;
};
}
#define MDECK_STEAM_SCOPE(stage) FEXCore::SteamProbe::Scope mdeck_steam_scope(stage)
#else
#define MDECK_STEAM_SCOPE(stage) ((void)0)
#endif
