#ifndef MADEIRA_CHECKPOINT_EVENT_H
#define MADEIRA_CHECKPOINT_EVENT_H

#include <stdint.h>

struct object;
struct unicode_str;
struct security_descriptor;

/* Capture after all Wine requests and client-side sync operations are parked.
 * Names, security descriptors and handles belong to the enclosing object graph. */
struct ios_checkpoint_event
{
    uint32_t manual_reset, signaled;
};

unsigned int ios_checkpoint_capture_event(struct object *, struct ios_checkpoint_event *);
struct object *ios_checkpoint_restore_event(const struct ios_checkpoint_event *, struct object *,
                                            const struct unicode_str *, unsigned int,
                                            const struct security_descriptor *);
#endif
