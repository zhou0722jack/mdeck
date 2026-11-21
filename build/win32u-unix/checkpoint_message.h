#ifndef MADEIRA_CHECKPOINT_MESSAGE_H
#define MADEIRA_CHECKPOINT_MESSAGE_H

#include <stdint.h>
#include <stddef.h>

/* Captured at the pending NtWaitForMultipleObjects in wait_message. The
 * owning syscall and its lower-level wait must be restored together. */
struct ios_checkpoint_message_wait
{
    uint32_t version, tid, count, timeout;
    uint32_t wake_mask, changed_mask, flags, sliced;
    uint32_t restore_locks, locks;
    int64_t deadline, wait_deadline;
    uint32_t handles[64];
};

struct ios_message_wait;
unsigned int ios_checkpoint_capture_message_wait(const struct ios_message_wait *, uint32_t tid,
                                                 struct ios_checkpoint_message_wait *);
/* wake is the completed NT wait result, after ntdll has processed APCs. */
unsigned int ios_checkpoint_resume_message_wait(const struct ios_checkpoint_message_wait *,
                                                uint32_t wake, uint32_t *result);

/* At this boundary the thunk lock has been dropped and the next lower
 * wait has not been issued. A fresh thread must issue that wait once. */
unsigned int ios_checkpoint_restart_message_wait(const struct ios_checkpoint_message_wait *, uint32_t *result);

/* The caller supplies the exact threads it needs at this boundary. The
 * visitor runs on its calling thread while all listed owners are parked.
 * Other Wine threads, the server and drivers require their own barriers. */
typedef unsigned int (*ios_checkpoint_visit_messages)(const struct ios_checkpoint_message_wait *,
                                                      size_t count, void *context);
unsigned int ios_checkpoint_hold_messages(const uint32_t *tids, size_t count, uint32_t timeout_ms,
                                         ios_checkpoint_visit_messages, void *context);
#endif
