#include "../checkpoint_session.h"

struct message_session_capture
{
    struct ios_checkpoint_roster roster;
    const struct ios_checkpoint_message_wait *messages;
    ios_checkpoint_session_visitor visit;
    void *context;
    uint64_t deadline;
};

static uint32_t checkpoint_remaining_ms(uint64_t deadline)
{
    uint64_t now = clock_gettime_nsec_np(CLOCK_MONOTONIC);
    return now < deadline ? (uint32_t)((deadline - now + 999999) / 1000000) : 0;
}

static unsigned int checkpoint_visit_message_session(void *context)
{
    struct message_session_capture *capture = context;
    return capture->visit(&capture->roster, capture->messages, capture->context);
}

static unsigned int checkpoint_lock_message_session(const struct ios_checkpoint_message_wait *messages,
                                                     size_t count, void *context)
{
    struct message_session_capture *capture = context;
    if (count != capture->roster.count) return STATUS_RETRY;
    for (size_t i = 0; i < count; ++i)
        if (messages[i].tid != capture->roster.clients[i].tid) return STATUS_RETRY;
    uint32_t remaining = checkpoint_remaining_ms(capture->deadline);
    if (!remaining) return STATUS_TIMEOUT;
    capture->messages = messages;
    return ios_checkpoint_visit_parked(&capture->roster, remaining, checkpoint_visit_message_session, capture);
}

unsigned int ios_checkpoint_visit_message_session(uint32_t timeout_ms,
    ios_checkpoint_session_visitor visit, void *context)
{
    if (!timeout_ms || !visit) return STATUS_INVALID_PARAMETER;
    struct message_session_capture capture = {
        .visit = visit, .context = context,
        .deadline = clock_gettime_nsec_np(CLOCK_MONOTONIC) + (uint64_t)timeout_ms * 1000000,
    };
    uint32_t *tids = NULL;
    unsigned int status = ios_checkpoint_get_roster(&capture.roster, timeout_ms);
    if (status) return status;
    if (!capture.roster.count) status = STATUS_PROCESS_IS_TERMINATING;
    else if (!(tids = calloc(capture.roster.count, sizeof(*tids)))) status = STATUS_NO_MEMORY;
    else
    {
        for (size_t i = 0; i < capture.roster.count; ++i) tids[i] = capture.roster.clients[i].tid;
        uint32_t remaining = checkpoint_remaining_ms(capture.deadline);
        status = remaining ? ios_checkpoint_hold_messages(tids, capture.roster.count, remaining,
                                                           checkpoint_lock_message_session, &capture) : STATUS_TIMEOUT;
    }
    free(tids);
    free(capture.roster.clients);
    return status;
}
