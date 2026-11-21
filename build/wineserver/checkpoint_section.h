/* The enclosing checkpoint supplies a private directory, the section's size
 * and a unique object ID. All views/handles of one section must use that ID.
 * Capture requires quiescent writers. Import requires a new, unpublished
 * backing of exactly the requested size. Discard it on any error. */
#ifndef MADEIRA_CHECKPOINT_SECTION_H
#define MADEIRA_CHECKPOINT_SECTION_H

#include <stdint.h>

int madeira_save_section_bytes(int directory, uint64_t id, int backing, uint64_t size);
int madeira_load_section_bytes(int directory, uint64_t id, int backing, uint64_t size);

#endif
