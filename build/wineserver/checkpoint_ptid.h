#ifndef MADEIRA_CHECKPOINT_PTID_H
#define MADEIRA_CHECKPOINT_PTID_H

#include <stdint.h>

struct object;
typedef unsigned int (*ios_checkpoint_visit_ptid)(void *, uint32_t, struct object *);
typedef unsigned int (*ios_checkpoint_create_ptid)(void *, uint32_t, struct object **);

/* Capture visits live entries in order. issued counts all IDs ever handed
 * out, including IDs whose objects have since died. A restore into a fresh
 * server consumes records in that order. Each callback constructs exactly
 * one object. A failed constructor invalidates the unpublished session. */
unsigned int ios_checkpoint_capture_ptids(ios_checkpoint_visit_ptid, void *, uint32_t *issued);
unsigned int ios_checkpoint_restore_ptid(uint32_t, ios_checkpoint_create_ptid, void *);
unsigned int ios_checkpoint_finish_ptids(uint32_t issued);
#endif
