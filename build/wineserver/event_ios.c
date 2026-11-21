#include "../../wine/server/event.c"
#include "checkpoint_event.h"
#include <linux/ntsync.h>

unsigned int ios_checkpoint_capture_event(struct object *obj, struct ios_checkpoint_event *out)
{
    struct event *event;
    if (!obj || !out) return STATUS_INVALID_PARAMETER;
    if (obj->ops != &event_ops) return STATUS_OBJECT_TYPE_MISMATCH;
    event = (struct event *)obj;
    if (!event->sync) return STATUS_INVALID_HANDLE;
    if (event->sync->ops == &event_sync_ops)
    {
        struct event_sync *sync = (struct event_sync *)event->sync;
        *out = (struct ios_checkpoint_event){sync->manual, event_sync_state(sync)};
        return STATUS_SUCCESS;
    }
    /* create_event_sync selects an inproc event when madsync is active. */
    struct ntsync_event_args args;
    int fd = get_inproc_sync_fd((struct inproc_sync *)event->sync);
    if (madsync_ioctl(fd, NTSYNC_IOC_EVENT_READ, &args) < 0) return STATUS_INVALID_HANDLE;
    *out = (struct ios_checkpoint_event){args.manual, args.signaled};
    return STATUS_SUCCESS;
}

struct object *ios_checkpoint_restore_event(const struct ios_checkpoint_event *record, struct object *root,
                                            const struct unicode_str *name, unsigned int attr,
                                            const struct security_descriptor *sd)
{
    if (!record || record->manual_reset > 1 || record->signaled > 1)
    {
        set_error(STATUS_INVALID_PARAMETER);
        return NULL;
    }
    struct event *event = create_event(root, name, attr, record->manual_reset, record->signaled, sd);
    if (!event) return NULL;
    if (get_error() == STATUS_OBJECT_NAME_EXISTS)
    {
        release_object(event);
        set_error(STATUS_OBJECT_NAME_COLLISION);
        return NULL;
    }
    return &event->obj;
}
