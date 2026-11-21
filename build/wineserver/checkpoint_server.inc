/* Included in fd_ios.c, which owns the server loop and the direct-request
 * lock. Only the caller owns the storage behind a pending request. */
#include "checkpoint_server.h"

struct checkpoint_request
{
    unsigned int (*run)(void *);
    void *context;
    uint64_t session;
    unsigned int status;
    int started, done;
};

static pthread_mutex_t checkpoint_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t checkpoint_changed = PTHREAD_COND_INITIALIZER;
static uint64_t checkpoint_serial, checkpoint_session;
static struct checkpoint_request *checkpoint_pending;

static void checkpoint_server_start(void)
{
    pthread_mutex_lock(&checkpoint_mutex);
    if (!++checkpoint_serial) ++checkpoint_serial;
    checkpoint_session = checkpoint_serial;
    pthread_mutex_unlock(&checkpoint_mutex);
}

static void checkpoint_server_stop(void)
{
    pthread_mutex_lock(&checkpoint_mutex);
    checkpoint_session = 0;
    struct checkpoint_request *req = __atomic_load_n(&checkpoint_pending, __ATOMIC_RELAXED);
    if (req)
    {
        req->status = STATUS_PROCESS_IS_TERMINATING;
        req->done = 1;
        __atomic_store_n(&checkpoint_pending, NULL, __ATOMIC_RELEASE);
        pthread_cond_broadcast(&checkpoint_changed);
    }
    pthread_mutex_unlock(&checkpoint_mutex);
}

static void checkpoint_server_dispatch(void)
{
    if (!__atomic_load_n(&checkpoint_pending, __ATOMIC_ACQUIRE)) return;
    pthread_mutex_lock(&checkpoint_mutex);
    struct checkpoint_request *req = __atomic_load_n(&checkpoint_pending, __ATOMIC_RELAXED);
    if (req)
    {
        req->started = 1;
        pthread_mutex_unlock(&checkpoint_mutex);
        unsigned int status = req->run(req->context);
        pthread_mutex_lock(&checkpoint_mutex);
        req->status = status;
        req->done = 1;
        __atomic_store_n(&checkpoint_pending, NULL, __ATOMIC_RELEASE);
        pthread_cond_broadcast(&checkpoint_changed);
    }
    pthread_mutex_unlock(&checkpoint_mutex);
}

static unsigned int checkpoint_submit(struct checkpoint_request *req, uint32_t timeout_ms)
{
    if (!timeout_ms) return STATUS_INVALID_PARAMETER;
    int cancel;
    pthread_setcancelstate(PTHREAD_CANCEL_DISABLE, &cancel);
    pthread_mutex_lock(&checkpoint_mutex);
    unsigned int status = STATUS_DEVICE_BUSY;
    if (!checkpoint_session || (req->session && req->session != checkpoint_session))
        status = STATUS_PROCESS_IS_TERMINATING;
    else if (!__atomic_load_n(&checkpoint_pending, __ATOMIC_RELAXED))
    {
        req->session = checkpoint_session;
        uint64_t deadline = clock_gettime_nsec_np(CLOCK_MONOTONIC) + (uint64_t)timeout_ms * 1000000;
        __atomic_store_n(&checkpoint_pending, req, __ATOMIC_RELEASE);
        ios_wineserver_wake();
        while (!req->done)
        {
            if (req->started)
            {
                pthread_cond_wait(&checkpoint_changed, &checkpoint_mutex);
                continue;
            }
            uint64_t now = clock_gettime_nsec_np(CLOCK_MONOTONIC);
            if (now >= deadline) break;
            uint64_t left = deadline - now;
            struct timespec ts = {left / 1000000000, left % 1000000000};
            int err = pthread_cond_timedwait_relative_np(&checkpoint_changed, &checkpoint_mutex, &ts);
            if (err && err != ETIMEDOUT && !req->started) break;
        }
        if (req->done) status = req->status;
        else
        {
            __atomic_store_n(&checkpoint_pending, NULL, __ATOMIC_RELEASE);
            status = STATUS_TIMEOUT;
        }
    }
    pthread_mutex_unlock(&checkpoint_mutex);
    pthread_setcancelstate(cancel, NULL);
    return status;
}

struct checkpoint_collect
{
    struct ios_checkpoint_roster roster;
    size_t capacity;
    unsigned int error;
};

static int checkpoint_collect_process(struct process *process, void *context)
{
    struct checkpoint_collect *out = context;
    struct thread *thread;
    LIST_FOR_EACH_ENTRY(thread, &process->thread_list, struct thread, proc_entry)
    {
        if (out->roster.count == out->capacity)
        {
            if (out->capacity > SIZE_MAX / 2 / sizeof(*out->roster.clients))
            {
                out->error = STATUS_NO_MEMORY;
                return 1;
            }
            size_t capacity = out->capacity ? out->capacity * 2 : 32;
            void *clients = realloc(out->roster.clients, capacity * sizeof(*out->roster.clients));
            if (!clients) { out->error = STATUS_NO_MEMORY; return 1; }
            out->roster.clients = clients;
            out->capacity = capacity;
        }
        out->roster.clients[out->roster.count++] = (struct ios_checkpoint_client){process->id, thread->id};
    }
    return 0;
}

static unsigned int checkpoint_collect_clients(void *context)
{
    struct checkpoint_collect *out = context;
    enum_processes(checkpoint_collect_process, out);
    return out->error;
}

unsigned int ios_checkpoint_get_roster(struct ios_checkpoint_roster *roster, uint32_t timeout_ms)
{
    if (!roster) return STATUS_INVALID_PARAMETER;
    struct checkpoint_collect out = {0};
    struct checkpoint_request req = {.run = checkpoint_collect_clients, .context = &out};
    unsigned int status = checkpoint_submit(&req, timeout_ms);
    if (status) free(out.roster.clients);
    else
    {
        out.roster.session = req.session;
        *roster = out.roster;
    }
    return status;
}

struct checkpoint_visit
{
    const struct ios_checkpoint_roster *expected;
    unsigned int (*visit)(void *);
    void *context;
};

static unsigned int checkpoint_verify_and_visit(void *context)
{
    struct checkpoint_visit *call = context;
    struct checkpoint_collect actual = {0};
    unsigned int status = checkpoint_collect_clients(&actual);
    if (!status && (actual.roster.count != call->expected->count ||
        memcmp(actual.roster.clients, call->expected->clients, actual.roster.count * sizeof(*actual.roster.clients))))
        status = STATUS_RETRY;
    free(actual.roster.clients);
    return status ? status : call->visit(call->context);
}

unsigned int ios_checkpoint_visit_parked(const struct ios_checkpoint_roster *roster,
                                         uint32_t timeout_ms, unsigned int (*visit)(void *), void *context)
{
    if (!roster || !roster->session || !roster->count || !roster->clients || !visit) return STATUS_INVALID_PARAMETER;
    struct checkpoint_visit call = {roster, visit, context};
    struct checkpoint_request req = {.run = checkpoint_verify_and_visit, .context = &call,
                                     .session = roster->session};
    return checkpoint_submit(&req, timeout_ms);
}
