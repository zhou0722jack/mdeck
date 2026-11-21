/* Run on macOS with clang -pthread -fsanitize=address,undefined. */
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include "../../build/win32u-unix/checkpoint_message.h"

#define STATUS_SUCCESS 0
#define STATUS_TIMEOUT 258
#define STATUS_DEVICE_BUSY 0x80000011u
#define STATUS_INVALID_PARAMETER 0xc000000du
#define STATUS_NO_MEMORY 0xc0000017u
#define STATUS_UNSUCCESSFUL 0xc0000001u
static _Thread_local struct { struct { uint32_t UniqueThread; } ClientId; } teb;
#define NtCurrentTeb() (&teb)
#define HandleToULong(x) (x)
struct ios_message_wait { uint32_t token; };
unsigned int ios_checkpoint_capture_message_wait(const struct ios_message_wait *frame, uint32_t tid,
                                                struct ios_checkpoint_message_wait *record)
{
    *record = (struct ios_checkpoint_message_wait){.tid = tid, .handles = {frame->token}};
    return STATUS_SUCCESS;
}
#include "../../build/win32u-unix/checkpoint_message_hold.inc"

static unsigned int finished, visits;
static uint32_t tids[] = {12, 4};
static void *worker(void *p)
{
    teb.ClientId.UniqueThread = *(uint32_t *)p;
    struct ios_message_wait frame = {.token = teb.ClientId.UniqueThread * 4};
    while (!__atomic_load_n(&message_hold_epoch, __ATOMIC_ACQUIRE)) sched_yield();
    checkpoint_before_message_wait(&frame);
    __atomic_fetch_add(&finished, 1, __ATOMIC_RELEASE);
    return NULL;
}
static unsigned int inspect(const struct ios_checkpoint_message_wait *records, size_t count, void *ctx)
{
    ++visits;
    assert(count == 2 && !__atomic_load_n(&finished, __ATOMIC_ACQUIRE));
    for (size_t i = 0; i < count; ++i)
        assert(records[i].tid == tids[i] && records[i].handles[0] == tids[i] * 4);
    assert(ios_checkpoint_hold_messages(tids, 2, 100, inspect, NULL) == STATUS_DEVICE_BUSY);
    return *(unsigned int *)ctx;
}
int main(void)
{
    unsigned int result = STATUS_UNSUCCESSFUL;
    pthread_t workers[2];
    for (int i = 0; i < 2; ++i) assert(!pthread_create(&workers[i], NULL, worker, &tids[i]));
    assert(ios_checkpoint_hold_messages(tids, 2, 3000, inspect, &result) == result);
    for (int i = 0; i < 2; ++i) assert(!pthread_join(workers[i], NULL));
    assert(finished == 2 && visits == 1);
    assert(!pthread_create(&workers[0], NULL, worker, &tids[0]));
    assert(ios_checkpoint_hold_messages(tids, 2, 300, inspect, &result) == STATUS_TIMEOUT);
    assert(!pthread_join(workers[0], NULL) && visits == 1 && finished == 3);
    tids[1] = tids[0];
    assert(ios_checkpoint_hold_messages(tids, 2, 10, inspect, &result) == STATUS_INVALID_PARAMETER);
    puts("PASS both owners held, callback failure and timeout release all arrivals, concurrent request rejected");
}
