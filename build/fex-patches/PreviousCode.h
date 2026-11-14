// mdeck-owned opt-in policy and one-generation retention. No executable memory allocation.
#pragma once
#include <cstddef>
#include <utility>

namespace FEXCore::MDeckPrevious {
inline unsigned Policy {}; // 0=unselected, 1=off, 2=CEF opt-in
inline bool Configure(const char* value, bool cef) {
  unsigned expected = 0;
  const bool on = cef && value && value[0] == '1' && value[1] == 0;
  __atomic_compare_exchange_n(&Policy, &expected, on ? 2u : 1u, false, __ATOMIC_RELEASE, __ATOMIC_RELAXED);
  return __atomic_load_n(&Policy, __ATOMIC_ACQUIRE) == 2;
}
inline bool Enabled() {
#if defined(FEX_IOS_HOST) && defined(_WIN32)
  const unsigned p = __atomic_load_n(&Policy, __ATOMIC_ACQUIRE);
  return p ? p == 2 : Configure(nullptr, false);
#else
  return false;
#endif
}
// Externally serialized by LatestMutex. Return retired refs to the caller so
// their destructor (VirtualFree / notifications) runs AFTER that leaf lock.
template<typename Pointer> struct Slot {
  static constexpr std::size_t Budget = 128u * 1024u * 1024u;
  Pointer Previous;
  bool Stopped {};
  Pointer Rotate(const Pointer& outgoing, bool enabled, bool capacity, std::size_t bytes) {
    auto retired = std::move(Previous);
    if (outgoing && !capacity) Stopped = true; // explicit clear: fail closed until restart
    if (enabled && !Stopped && capacity && outgoing && bytes <= Budget) Previous = outgoing;
    return retired;
  }
  Pointer Stop() { Stopped = true; return std::move(Previous); }
};
}
