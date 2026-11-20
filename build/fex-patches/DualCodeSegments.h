// mdeck-owned policy and lifetime for an optional second executable segment.
#pragma once

#include <cstddef>
#include <cstdint>
#include <FEXCore/Utils/IOSJITRegions.h>

namespace FEXCore::MDeckSegments {
inline constexpr unsigned SizeShift = 27;
inline constexpr std::size_t Bytes = std::size_t {1} << SizeShift;
inline unsigned Policy {}; // 0 unconfigured, 1 off, 2 CEF opt-in
inline Allocator::IOSJIT::Range MainPool {}, LowPool {};

// Called once in each PE module's process init, before any JIT threads start.
inline bool Configure(const char* Value, bool CEF, const char* RX, const char* Size, const char* RW, const char* Low) {
  if (const auto State = __atomic_load_n(&Policy, __ATOMIC_ACQUIRE)) return State == 2;
  using namespace Allocator::IOSJIT;
  const auto Parse = [](const char* Text) -> uintptr_t {
    uintptr_t Number = 0;
    return Text && Hex(Text, Number) && !*Text ? Number : 0;
  };
  const Range Main {Parse(RX), Parse(Size)};
  const auto Write = Parse(RW);
  Range Other {};
  const bool On = CEF && Value && Value[0] == '1' && Value[1] == 0 && Main.Valid() &&
                  Range {Write, Main.Size}.Valid() && Write != Main.Base && ParseLow(Low, Main, Write, Other);
  if (On) { MainPool = Main; LowPool = Other; }
  __atomic_store_n(&Policy, On ? 2u : 1u, __ATOMIC_RELEASE);
  return On;
}
inline bool PoolContains(uintptr_t PC, std::size_t Length) {
  return Allocator::IOSJIT::Allowed(MainPool, LowPool, PC, Length);
}
inline bool Enabled() {
#if defined(FEX_IOS_HOST) && defined(_WIN32)
  return __atomic_load_n(&Policy, __ATOMIC_ACQUIRE) == 2;
#else
  return false;
#endif
}

// One extra segment per PE module, including retired owners still pinned by
// running threads or exception frames. The executable allocator separately
// enforces its shared pool/code budget; this never bypasses that allocator.
inline unsigned Reserved {};
struct BudgetOwner {
  unsigned PID {};
  uint64_t Manager {};
  uint64_t PrimaryGeneration {};
  uint64_t Generation {};
  uintptr_t PrimaryRX {};
  uintptr_t SecondRX {};
};
inline BudgetOwner PublishedOwner {};

inline BudgetOwner ReadBudgetOwner() {
  const auto Generation = __atomic_load_n(&PublishedOwner.Generation, __ATOMIC_SEQ_CST);
  if (!Generation) return {};
  BudgetOwner Owner {
    __atomic_load_n(&PublishedOwner.PID, __ATOMIC_SEQ_CST),
    __atomic_load_n(&PublishedOwner.Manager, __ATOMIC_SEQ_CST),
    __atomic_load_n(&PublishedOwner.PrimaryGeneration, __ATOMIC_SEQ_CST), Generation,
    __atomic_load_n(&PublishedOwner.PrimaryRX, __ATOMIC_SEQ_CST),
    __atomic_load_n(&PublishedOwner.SecondRX, __ATOMIC_SEQ_CST),
  };
  // The unique serial brackets publication. Ignore a release/reattach race.
  return Generation == __atomic_load_n(&PublishedOwner.Generation, __ATOMIC_SEQ_CST) ? Owner : BudgetOwner {};
}
// Also read with LDAR in emitted indirect-exit code. Use a naturally aligned
// integer (not the representation of std::atomic) and pair with release stores.
alignas(sizeof(uintptr_t)) inline uintptr_t ActiveSecondRX {};

constexpr bool Contains(uintptr_t Base, std::size_t Size, uintptr_t PC) {
  return Base && PC - Base < Size;
}
constexpr bool Fits(std::size_t Capacity, std::size_t Offset, std::size_t Count) {
  return Offset <= Capacity && Count <= Capacity - Offset;
}
enum class Segment : uint8_t { First, Second, Outside };
constexpr Segment Classify(uintptr_t First, std::size_t FirstUsable, uintptr_t Second, std::size_t Guard, uintptr_t PC) {
  if (Contains(First, FirstUsable, PC)) return Segment::First;
  if (Guard < Bytes && Contains(Second, Bytes - Guard, PC)) return Segment::Second;
  return Segment::Outside;
}

enum class Append { Added, AlreadyFull, Budget, AllocationFailed, TooLarge };
constexpr const char* AppendName(Append Result) {
  switch (Result) {
  case Append::Added: return "added";
  case Append::AlreadyFull: return "second-full";
  case Append::Budget: return "extra-budget";
  case Append::AllocationFailed: return "alloc-failed";
  case Append::TooLarge: return "too-large";
  }
  return "unknown";
}

class SecondSegment {
  using Free = void (*)(void*, std::size_t);
  using ReleaseReport = void (*)(const BudgetOwner&);
  uintptr_t RX {};
  Free Release {};
  ReleaseReport ReportRelease {};
  BudgetOwner Owner {};

public:
  // Only the normal emission writer accesses offset/id. Initialization of both
  // precedes publishing RX; a reader must never use the first segment's offset
  // with the second segment (including interrupted delivery on the same thread).
  std::size_t Offset {};
  uint64_t Generation {};

  SecondSegment() = default;
  SecondSegment(const SecondSegment&) = delete;
  SecondSegment& operator=(const SecondSegment&) = delete;
  ~SecondSegment() {
    if (const auto Base = Address()) {
      // No group refs remain. Clear the emitted lookup guard before this VA can
      // be reused, but don't release the budget until VirtualFree returns.
      __atomic_store_n(&ActiveSecondRX, uintptr_t {}, __ATOMIC_RELEASE);
      Release(reinterpret_cast<void*>(Base), Bytes);
      __atomic_store_n(&PublishedOwner.Generation, uint64_t {}, __ATOMIC_SEQ_CST);
      __atomic_store_n(&Reserved, 0u, __ATOMIC_RELEASE);
      if (ReportRelease) ReportRelease(Owner);
    }
  }

  uintptr_t Address() const { return __atomic_load_n(&RX, __ATOMIC_ACQUIRE); }
  const BudgetOwner& AttachedOwner() const { return Owner; }

  template<typename Alloc, typename NewId>
  Append TryAttach(std::size_t Required, std::size_t Guard, Alloc Allocate, Free FreeRegion, NewId GetId,
                   BudgetOwner Identity = {}, ReleaseReport OnRelease = nullptr) {
    if (Address()) return Append::AlreadyFull;
    if (Guard >= Bytes || !Fits(Bytes - Guard, 0, Required)) return Append::TooLarge;
    unsigned Expected = 0;
    if (!__atomic_compare_exchange_n(&Reserved, &Expected, 1u, false, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) return Append::Budget;
    if (const auto Base = reinterpret_cast<uintptr_t>(Allocate(Bytes))) {
      Release = FreeRegion;
      ReportRelease = OnRelease;
      Generation = GetId();
      Identity.Generation = Generation;
      Identity.SecondRX = Base;
      Owner = Identity;
      __atomic_store_n(&PublishedOwner.PID, Owner.PID, __ATOMIC_SEQ_CST);
      __atomic_store_n(&PublishedOwner.Manager, Owner.Manager, __ATOMIC_SEQ_CST);
      __atomic_store_n(&PublishedOwner.PrimaryGeneration, Owner.PrimaryGeneration, __ATOMIC_SEQ_CST);
      __atomic_store_n(&PublishedOwner.PrimaryRX, Owner.PrimaryRX, __ATOMIC_SEQ_CST);
      __atomic_store_n(&PublishedOwner.SecondRX, Owner.SecondRX, __ATOMIC_SEQ_CST);
      __atomic_store_n(&PublishedOwner.Generation, Owner.Generation, __ATOMIC_SEQ_CST);
      // The emitted guard must see the physical range before any thread can
      // publish a guest entry pointing into it.
      __atomic_store_n(&ActiveSecondRX, Base, __ATOMIC_RELEASE);
      __atomic_store_n(&RX, Base, __ATOMIC_RELEASE);
      return Append::Added;
    }
    __atomic_store_n(&Reserved, 0u, __ATOMIC_RELEASE);
    return Append::AllocationFailed;
  }
};
}
