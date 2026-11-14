// mdeck-owned DFE scratch storage. No IR analysis or propagation rules here.
#pragma once
#include <cstddef>
#include <optional>
#include <utility>

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
    explicit Lease(DFEScratch& Owner) : Owner(Owner), Borrowed(!Owner.Busy) {
      if (Borrowed) { Owner.Busy = true; Data = &Owner.Data; }
      else Data = &Fallback.emplace();
    }
    ~Lease() {
      Data->Reset();
      if (Borrowed) Owner.Busy = false;
    }
    Storage& Get() { return *Data; }
    Lease(const Lease&) = delete;
    Lease& operator=(const Lease&) = delete;
  };
private:
  Storage Data;
  bool Busy {};
};
}
