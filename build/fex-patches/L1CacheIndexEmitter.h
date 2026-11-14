// SPDX-License-Identifier: MIT
#pragma once
#include <FEXCore/Utils/L1CacheIndex.h>
#include <CodeEmitter/Emitter.h>

namespace FEXCore::MDeckL1 {
// Used by every emitted L1 read and refill. Only address/temp are clobbered;
// RIP, state, the L2 hit's host target and guest NZCV remain untouched. No
// runtime feature branch or added cache allocation. pointerOffset names the
// adjacent L1Pointer/L1Mask pair in CpuStateFrame.
inline void EmitAddress(ARMEmitter::Emitter& code, ARMEmitter::Register address,
                        ARMEmitter::Register temp, ARMEmitter::Register state,
                        ARMEmitter::Register rip, uint32_t pointerOffset, bool mixed) {
  using namespace ARMEmitter;
  if (mixed) {
    code.eor(Size::i64Bit, address, rip, rip, ShiftType::LSR, 16);
    code.eor(Size::i64Bit, address, address, address, ShiftType::LSR, 32);
    code.ldr(temp.X(), state.X(), pointerOffset + 8);
    code.and_(Size::i64Bit, temp, temp, address, ShiftType::LSL, 4);
    code.ldr(address.X(), state.X(), pointerOffset);
  } else {
    code.ldp<IndexType::OFFSET>(address.X(), temp.X(), state.X(), pointerOffset);
    code.and_(Size::i64Bit, temp, temp, rip, ShiftType::LSL, 4);
  }
  code.add(address.X(), address.X(), temp.X());
}
}
