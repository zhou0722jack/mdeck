/* Included by the iOS message pump. Only the explicit capture request
 * takes a lock on the wait path. Each owner publishes its own frame. */
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include <time.h>

static pthread_mutex_t message_hold_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t message_hold_changed = PTHREAD_COND_INITIALIZER;
static uint64_t message_hold_epoch, message_hold_serial;
static struct ios_checkpoint_message_wait *message_hold_records;
static const uint32_t *message_hold_tids;
static size_t message_hold_count, message_hold_ready;
static unsigned int message_hold_error;

static void checkpoint_before_message_wait(const struct ios_message_wait *wait)
{
    uint64_t epoch = __atomic_load_n(&message_hold_epoch, __ATOMIC_ACQUIRE);
    if (!epoch) return;
    uint32_t tid = HandleToULong(NtCurrentTeb()->ClientId.UniqueThread);
    int cancel;
    pthread_setcancelstate(PTHREAD_CANCEL_DISABLE, &cancel);
    pthread_mutex_lock(&message_hold_mutex);
    if (__atomic_load_n(&message_hold_epoch, __ATOMIC_RELAXED) == epoch)
    {
        for (size_t i = 0; i < message_hold_count; ++i)
        {
            if (tid != message_hold_tids[i]) continue;
            unsigned int status = message_hold_records[i].tid ? STATUS_INVALID_PARAMETER :
                ios_checkpoint_capture_message_wait(wait, tid, &message_hold_records[i]);
            if (status) message_hold_error = status;
            else ++message_hold_ready;
            pthread_cond_broadcast(&message_hold_changed);
            while (__atomic_load_n(&message_hold_epoch, __ATOMIC_RELAXED) == epoch)
                pthread_cond_wait(&message_hold_changed, &message_hold_mutex);
            break;
        }
    }
    pthread_mutex_unlock(&message_hold_mutex);
    pthread_setcancelstate(cancel, NULL);
}

unsigned int ios_checkpoint_hold_messages(const uint32_t *tids, size_t count, uint32_t timeout_ms,
                                         ios_checkpoint_visit_messages visit, void *context)
{
    if (!tids || !count || !visit || !timeout_ms) return STATUS_INVALID_PARAMETER;
    for (size_t i = 0; i < count; ++i)
    {
        if (!tids[i]) return STATUS_INVALID_PARAMETER;
        for (size_t j = 0; j < i; ++j)
            if (tids[j] == tids[i]) return STATUS_INVALID_PARAMETER;
    }
    struct ios_checkpoint_message_wait *records = calloc(count, sizeof(*records));
    if (!records) return STATUS_NO_MEMORY;
    uint64_t deadline = clock_gettime_nsec_np(CLOCK_MONOTONIC) + (uint64_t)timeout_ms * 1000000;
    int cancel;
    pthread_setcancelstate(PTHREAD_CANCEL_DISABLE, &cancel);
    pthread_mutex_lock(&message_hold_mutex);
    unsigned int status = STATUS_DEVICE_BUSY;
    if (!__atomic_load_n(&message_hold_epoch, __ATOMIC_RELAXED))
    {
        message_hold_tids = tids;
        message_hold_records = records;
        message_hold_count = count;
        message_hold_ready = 0;
        message_hold_error = 0;
        if (!++message_hold_serial) ++message_hold_serial;
        __atomic_store_n(&message_hold_epoch, message_hold_serial, __ATOMIC_RELEASE);
        while (message_hold_ready < count && !message_hold_error)
        {
            uint64_t now = clock_gettime_nsec_np(CLOCK_MONOTONIC);
            if (now >= deadline) break;
            uint64_t left = deadline - now;
            struct timespec delay = {left / 1000000000, left % 1000000000};
            int err = pthread_cond_timedwait_relative_np(&message_hold_changed, &message_hold_mutex, &delay);
            if (err && err != ETIMEDOUT) { message_hold_error = STATUS_UNSUCCESSFUL; break; }
        }
        status = message_hold_error ? message_hold_error : STATUS_TIMEOUT;
        if (!message_hold_error && message_hold_ready == count)
        {
            /* Leave acquisition available so a concurrent request observes
             * the busy epoch. All named threads stay parked until release. */
            pthread_mutex_unlock(&message_hold_mutex);
            status = visit(records, count, context);
            pthread_mutex_lock(&message_hold_mutex);
        }
        message_hold_records = NULL;
        message_hold_tids = NULL;
        message_hold_count = 0;
        __atomic_store_n(&message_hold_epoch, 0, __ATOMIC_RELEASE);
        pthread_cond_broadcast(&message_hold_changed);
    }
    pthread_mutex_unlock(&message_hold_mutex);
    free(records);
    pthread_setcancelstate(cancel, NULL);
    return status;
}
