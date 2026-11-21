/* Called on the Wine server thread while requests and object changes are
 * stopped. Object IDs belong to the enclosing checkpoint's object table.
 * The old client's stack cookie is deliberately absent from the record. */
#ifndef MADEIRA_CHECKPOINT_WAIT_H
#define MADEIRA_CHECKPOINT_WAIT_H

#include "checkpoint_handles.h"

struct object;
struct thread;

struct ios_checkpoint_wait
{
    uint32_t version, tid, operation, flags, count, reserved;
    int64_t deadline;
    uint64_t objects[64];
    uint32_t queue_positions[64];
};

unsigned int ios_checkpoint_capture_wait(struct thread *, ios_checkpoint_object_id, void *,
                                         struct ios_checkpoint_wait *);
/* current is the restored waiter. Use a cookie supplied by its new client.
 * STATUS_RETRY means an earlier waiter in one of the queues must attach first.
 * Wakeups and timers may run only after the whole restore has been published. */
unsigned int ios_checkpoint_restore_wait(const struct ios_checkpoint_wait *, uint64_t,
                                         ios_checkpoint_find_object, void *);
#endif
