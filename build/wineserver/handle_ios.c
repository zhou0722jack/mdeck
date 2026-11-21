/* The slot allocation and reference-count rules belong to Wine's handle.c. */
#include "../../wine/server/handle.c"
#include "checkpoint_handles.h"

unsigned int ios_checkpoint_capture_handles(struct process *process, ios_checkpoint_object_id identify,
                                           void *objects, struct ios_checkpoint_handle **out,
                                           unsigned int *out_count)
{
    struct handle_table *table;
    struct ios_checkpoint_handle *records = NULL;
    unsigned int count = 0;
    if (!process || !(table = process->handles) || !identify || !out || !out_count)
        return STATUS_INVALID_PARAMETER;
    for (int i = 0; i <= table->last; ++i) count += table->entries[i].ptr != NULL;
    if (count && !(records = malloc(count * sizeof(*records)))) return STATUS_NO_MEMORY;
    count = 0;
    for (int i = 0; i <= table->last; ++i)
    {
        struct handle_entry *entry = &table->entries[i];
        if (!entry->ptr) continue;
        uint64_t id = identify(objects, entry->ptr);
        if (!id)
        {
            free(records);
            return STATUS_NOT_SUPPORTED;
        }
        records[count++] = (struct ios_checkpoint_handle){index_to_handle(i), entry->access, id};
    }
    *out = records;
    *out_count = count;
    return STATUS_SUCCESS;
}

unsigned int ios_checkpoint_restore_handles(struct process *process, const struct ios_checkpoint_handle *records,
                                           unsigned int count, ios_checkpoint_find_object lookup, void *objects)
{
    struct handle_table *table;
    obj_handle_t last = 0;
    if (!process || !lookup || (count && !records) || count > MAX_HANDLE_ENTRIES ||
        (process->handles && process->handles->last != -1)) return STATUS_INVALID_PARAMETER;
    for (unsigned int i = 0; i < count; ++i)
    {
        obj_handle_t h = records[i].handle;
        if (!records[i].object_id || h <= last || (h & 3) || h > index_to_handle(MAX_HANDLE_ENTRIES - 1))
            return STATUS_INVALID_PARAMETER;
        last = h;
    }
    /* An unpublished table has no owner, so unwinding a partial import
     * drops its references without sending close notifications to clients. */
    if (!(table = alloc_handle_table(NULL, last / 4))) return STATUS_NO_MEMORY;
    memset(table->entries, 0, (last / 4) * sizeof(*table->entries));
    for (unsigned int i = 0; i < count; ++i)
    {
        int index = handle_to_index(records[i].handle);
        struct object *obj = lookup(objects, records[i].object_id);
        if (!obj)
        {
            release_object(table);
            return STATUS_INVALID_HANDLE;
        }
        table->entries[index].ptr = grab_object_for_handle(obj);
        table->entries[index].access = records[i].access;
        table->last = index;
    }
    if (process->handles) release_object(process->handles);
    table->process = process;
    process->handles = table;
    return STATUS_SUCCESS;
}
