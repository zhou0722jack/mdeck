/* The numerical IDs stored in guest memory come from process.c's shared
 * process/thread registry. Restore uses the ordinary Wine constructors on
 * the server thread, before dispatching any client requests. */
#include "../../wine/server/process.c"
#include "checkpoint_ptid.h"

unsigned int ios_checkpoint_capture_ptids(ios_checkpoint_visit_ptid visit, void *context,
                                         uint32_t *issued)
{
    if (!visit || !issued) return STATUS_INVALID_PARAMETER;
    for (unsigned int i = 0; i < used_ptid_entries; ++i)
    {
        struct object *obj = ptid_entries[i].ptr;
        if (!obj) continue;
        unsigned int status = visit(context, ptid_from_index(PTID_OFFSET + i), obj);
        if (status) return status;
    }
    *issued = used_ptid_entries;
    return STATUS_SUCCESS;
}

/* Skip historical IDs which have already died. The iOS allocator never
 * reuses such IDs. Keep a spare slot so its next allocation is in bounds,
 * including when the first record follows a large gap. */
static unsigned int ios_checkpoint_skip_ptids(uint32_t count)
{
    if (count < used_ptid_entries || count >= UINT32_MAX / 4 - PTID_OFFSET)
        return STATUS_INVALID_PARAMETER;
    if (alloc_ptid_entries <= count)
    {
        unsigned int capacity = count + 1;
        if (capacity < 512) capacity = 512;
        size_t bytes;
        if (__builtin_mul_overflow((size_t)capacity, sizeof(*ptid_entries), &bytes)) return STATUS_NO_MEMORY;
        struct ptid_entry *entries = realloc(ptid_entries, bytes);
        if (!entries) return STATUS_NO_MEMORY;
        ptid_entries = entries;
        alloc_ptid_entries = capacity;
    }
    memset(ptid_entries + used_ptid_entries, 0, (count - used_ptid_entries) * sizeof(*ptid_entries));
    used_ptid_entries = count;
    return STATUS_SUCCESS;
}

unsigned int ios_checkpoint_restore_ptid(uint32_t id, ios_checkpoint_create_ptid create, void *context)
{
    unsigned int index = index_from_ptid(id);
    if (!create || (id & 3) || index < PTID_OFFSET) return STATUS_INVALID_PARAMETER;
    unsigned int status = ios_checkpoint_skip_ptids(index - PTID_OFFSET);
    if (status) return status;
    struct object *obj = NULL;
    status = create(context, id, &obj);
    if (status) return status;
    if (!obj || get_ptid_entry(id) != obj || used_ptid_entries != index - PTID_OFFSET + 1)
        return STATUS_INVALID_PARAMETER;
    return STATUS_SUCCESS;
}

unsigned int ios_checkpoint_finish_ptids(uint32_t issued)
{
    return ios_checkpoint_skip_ptids(issued);
}
