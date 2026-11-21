#ifndef MADEIRA_CHECKPOINT_VIEW_H
#define MADEIRA_CHECKPOINT_VIEW_H

#include <stdint.h>

/* All addresses on disk are relative to the owning WoW64 window. */
struct ios_checkpoint_view
{
    uint32_t version, pid, guest_base, protection;
    uint64_t size, offset, backing;
};

unsigned int ios_checkpoint_describe_view(uint32_t pid, uintptr_t peb, uintptr_t address,
                                         uint64_t size, uint64_t offset, uint64_t backing,
                                         struct ios_checkpoint_view *);
/* section_handle belongs to record->pid and resolves record->backing. */
unsigned int ios_checkpoint_attach_view(const struct ios_checkpoint_view *, void *section_handle);

#endif
