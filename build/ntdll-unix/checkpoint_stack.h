#ifndef MADEIRA_CHECKPOINT_STACK_H
#define MADEIRA_CHECKPOINT_STACK_H

#include <stdint.h>

struct ios_checkpoint_stack
{
    uint32_t version, pid, tid, allocation, limit, top, guard_size, guaranteed;
};

/* Called with all guest threads parked. A restore targets a freshly
 * allocated, unpublished thread at the same guest addresses. The caller
 * discards it if a copy fails. The byte span starts at the guard page. */
NTSTATUS ios_checkpoint_capture_stack(TEB *, struct ios_checkpoint_stack *, void *, size_t);
NTSTATUS ios_checkpoint_restore_stack(TEB *, const struct ios_checkpoint_stack *, const void *, size_t);
NTSTATUS ios_allocate_guest_stack(INITIAL_TEB *, ULONG_PTR, SIZE_T, SIZE_T);

#endif
