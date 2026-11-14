// mdeck-owned DFE scratch storage. No IR analysis or propagation rules here.
#pragma once
#include <cstddef>
#include <optional>
#include <utility>

namespace FEXCore::MDeckDFE {
// Each PE instance freezes its choice before InitCore creates any passes.
// Exact 0 disables; absent/other values preserve the Build 41 default.
inline unsigned Policy {}; // 0=unselected, 1=legacy allocation, 2=reuse
inline constexpr bool Parse(const char* value) {
  return !(value && value[0] == '0' && value[1] == 0);
}
inline bool Configure(const char* value) {
  unsigned expected = 0;
  __atomic_compare_exchange_n(&Policy, &expected, Parse(value) ? 2u : 1u,
                              false, __ATOMIC_RELEASE, __ATOMIC_RELAXED);
  return __atomic_load_n(&Policy, __ATOMIC_ACQUIRE) == 2;
}
inline bool Enabled() {
  const unsigned current = __atomic_load_n(&Policy, __ATOMIC_ACQUIRE);
  return current ? current == 2 : Configure(nullptr);
}
}

namespace FEXCore::IR {
// Container types are supplied by the caller (fextl in production). The deque
// operations and their ordering stay unchanged. A nested invocation owns a
// private fallback instead of borrowing live outer IR pointers.
template<typename Blocks, typename Seen, typename Queue>
class DFEScratch {
public:
  static constexpr std::size_t MaxRetainedBlocks = 4096;
  static constexpr std::size_t MaxRetainedPredecessors = 16384;
  struct Storage {
    Blocks BlockMap;
    Seen SeenIDs;
    Queue Worklist;
    void Reset() {
      std::size_t PredecessorCapacity = 0;
      for (auto& Block : BlockMap) {
        PredecessorCapacity += Block.Predecessors.capacity();
        Block.Predecessors.clear();
        Block.Node = nullptr;
        Block.Flags = 0;
        Block.InWorklist = false;
      }
      Worklist.clear();
      SeenIDs.clear();
      // Large one-off compilations may allocate freely while active, but don't
      // pin their scratch for the lifetime of the compiling thread.
      if (BlockMap.capacity() > MaxRetainedBlocks || PredecessorCapacity > MaxRetainedPredecessors) {
        Blocks {}.swap(BlockMap);
      }
      if (SeenIDs.capacity() > MaxRetainedBlocks) Seen {}.swap(SeenIDs);
    }
  };
  class Lease {
    DFEScratch& Owner;
    std::optional<Storage> Fallback;
    Storage* Data;
    bool Borrowed;
  public:
    explicit Lease(DFEScratch& Owner, bool Reuse = true) : Owner(Owner), Borrowed(Reuse && !Owner.Busy) {
      if (Borrowed) {
        // Lazily construct even the cached deque: off mode owns no idle scratch.
        Data = Owner.Data ? &*Owner.Data : &Owner.Data.emplace();
        Owner.Busy = true;
      } else Data = &Fallback.emplace();
    }
    ~Lease() {
      if (Borrowed) { Data->Reset(); Owner.Busy = false; }
      // Fresh/off and reentrant fallback storage is destroyed normally. No
      // extra cleanup walk is needed when none of its capacity is retained.
    }
    Storage& Get() { return *Data; }
    Lease(const Lease&) = delete;
    Lease& operator=(const Lease&) = delete;
  };
private:
  std::optional<Storage> Data;
  bool Busy {};
};
}
