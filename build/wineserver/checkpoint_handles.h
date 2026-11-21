#ifndef MADEIRA_CHECKPOINT_HANDLES_H
#define MADEIRA_CHECKPOINT_HANDLES_H

#include <stdint.h>

struct process;
struct object;
struct handle_table;

typedef uint64_t (*ios_checkpoint_object_id)(void *, struct object *);
typedef struct object *(*ios_checkpoint_find_object)(void *, uint64_t);

/* Local handles stored in guest memory must retain their numerical values.
 * The enclosing session owns IDs, serializes the record count and restores
 * the object table before any clients start sending requests. */
struct ios_checkpoint_handle
{
    uint32_t handle, access;
    uint64_t object_id;
};

unsigned int ios_checkpoint_capture_handles(struct process *, ios_checkpoint_object_id, void *,
                                           struct ios_checkpoint_handle **, unsigned int *);
unsigned int ios_checkpoint_restore_handles(struct process *, const struct ios_checkpoint_handle *,
                                           unsigned int, ios_checkpoint_find_object, void *);
#endif
