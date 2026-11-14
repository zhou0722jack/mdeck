// SPDX-License-Identifier: MIT
// mdeck-only experimental L1 indexing. No cache storage or lifetime changes.
#pragma once
#include <cstdint>

namespace FEXCore::MDeckL1 {
constexpr uint64_t Fold(uint64_t address) {
  address ^= address >> 16;
  return address ^ (address >> 32);
}
constexpr uint64_t Index(uint64_t address, uint64_t mask, bool mixed) {
  return (mixed ? Fold(address) : address) & mask;
}

#if defined(FEX_IOS_HOST) && defined(_WIN32)
// A PE instance chooses once, before InitCore emits its dispatcher. Reading
// before configuration freezes legacy mode, so a late environment change can
// never make C++ lookup disagree with code already emitted for that instance.
inline uint32_t Policy {}; // 0=unselected, 1=legacy, 2=fold16-v1
inline bool Configure(const char* value) {
  const uint32_t choice = value && value[0] == '1' && value[1] == 0 ? 2 : 1;
  uint32_t expected = 0;
  __atomic_compare_exchange_n(&Policy, &expected, choice, false, __ATOMIC_RELEASE, __ATOMIC_RELAXED);
  return __atomic_load_n(&Policy, __ATOMIC_ACQUIRE) == 2;
}
inline bool Enabled() {
  uint32_t current = __atomic_load_n(&Policy, __ATOMIC_ACQUIRE);
  if (!current) return Configure(nullptr);
  return current == 2;
}
#else
inline constexpr bool Enabled() { return false; }
#endif
}
