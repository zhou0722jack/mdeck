/* The checkpoint needs thread_wait and wait_on, both private to thread.c. */
#include "../../wine/server/thread.c"
#include "checkpoint_wait.h"

C_ASSERT(MAXIMUM_WAIT_OBJECTS == 64);

/* Queue insertion for plain waits is FIFO. Some Wine objects have private
 * queues; leave those to their own restore implementation. */
static int ios_checkpoint_queue_position(struct object *sync, const struct wait_queue_entry *target,
                                         uint32_t *position)
{
    struct list *entry;
    uint32_t index = 0;
    int found = 0;
    if (!sync) return 0;
    LIST_FOR_EACH(entry, &sync->wait_queue)
    {
        if (target && entry == &target->entry) { found = 1; break; }
        if (index == UINT32_MAX) break;
        ++index;
    }
    if (!target && entry == &sync->wait_queue) found = 1;
    if (found) *position = index;
    return found;
}

static int ios_checkpoint_plain_wait(unsigned int op, unsigned int flags, unsigned int count)
{
    if (count > MAXIMUM_WAIT_OBJECTS || flags & ~(SELECT_INTERRUPTIBLE | SELECT_ALERTABLE)) return 0;
    return op == SELECT_WAIT || op == SELECT_WAIT_ALL || (op == SELECT_NONE && !count);
}

unsigned int ios_checkpoint_capture_wait(struct thread *thread, ios_checkpoint_object_id identify,
                                         void *table, struct ios_checkpoint_wait *out)
{
    struct thread_wait *wait;
    struct ios_checkpoint_wait record = {0};
    if (!thread || !out || !identify) return STATUS_INVALID_PARAMETER;
    if (!(wait = thread->wait) || !wait->cookie || wait->next || thread->context || wait->abandoned ||
        wait->when == INT64_MIN ||
        !ios_checkpoint_plain_wait(wait->select, wait->flags, wait->count)) return STATUS_NOT_SUPPORTED;
    record.version = 1;
    record.tid = thread->id;
    record.operation = wait->select;
    record.flags = wait->flags;
    record.count = wait->count;
    /* Positive deadlines use wall time. Negative ones become remaining time
     * and start ticking again in the new session. */
    record.deadline = abstime_to_timeout(wait->when);
    for (unsigned int i = 0; i < record.count; ++i)
    {
        struct wait_queue_entry *entry = &wait->queues[i];
        struct object *sync = get_obj_sync(entry->obj);
        if (!sync) return STATUS_NOT_SUPPORTED;
        int linked = ios_checkpoint_queue_position(sync, entry, &record.queue_positions[i]);
        release_object(sync);
        if (!linked || !(record.objects[i] = identify(table, entry->obj))) return STATUS_NOT_SUPPORTED;
    }
    *out = record;
    return STATUS_SUCCESS;
}

unsigned int ios_checkpoint_restore_wait(const struct ios_checkpoint_wait *record, uint64_t cookie,
                                         ios_checkpoint_find_object lookup, void *table)
{
    struct object *objects[MAXIMUM_WAIT_OBJECTS], *syncs[MAXIMUM_WAIT_OBJECTS];
    union select_op op = {0};
    abstime_t when;
    unsigned int i, status = STATUS_INVALID_PARAMETER;
    if (!current || !record || !cookie || !lookup || current->wait || current->context ||
        record->version != 1 || record->reserved || record->tid != current->id ||
        !ios_checkpoint_plain_wait(record->operation, record->flags, record->count))
        return status;
    if (monotonic_time < 0 || record->deadline <= INT64_MIN + monotonic_time) return status;
    when = timeout_to_abstime(record->deadline);
    for (i = 0; i < record->count; ++i)
    {
        uint32_t position;
        struct object *obj = record->objects[i] ? lookup(table, record->objects[i]) : NULL;
        if (!obj || !obj->ops->get_sync || !(syncs[i] = get_obj_sync(obj))) goto done;
        if (!ios_checkpoint_queue_position(syncs[i], NULL, &position))
        {
            ++i;
            goto done;
        }
        objects[i] = obj;
        /* Different wrapper objects can share the same wait queue. Earlier
         * entries from this very wait will be appended by wait_on below. */
        uint64_t next = position;
        for (unsigned int j = 0; j < i; ++j) next += syncs[j] == syncs[i];
        if (next != record->queue_positions[i])
        {
            status = next < record->queue_positions[i] ? STATUS_RETRY : STATUS_INVALID_PARAMETER;
            ++i;
            goto done;
        }
    }
    op.op = record->operation;
    if (!wait_on(&op, record->count, objects, record->flags, when)) { status = get_error(); goto done; }
    if (when != TIMEOUT_INFINITE &&
        !(current->wait->user = add_timeout_user(abstime_to_timeout(when), thread_timeout, current->wait)))
    {
        status = get_error();
        end_wait(current, status);
        goto done;
    }
    current->wait->cookie = cookie;
    status = STATUS_SUCCESS;
done:
    while (i) release_object(syncs[--i]);
    return status;
}
