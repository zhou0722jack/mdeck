/* Build on macOS with clang -pthread -fsanitize=address,undefined. */
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "../../wine/include/wine/list.h"

#define STATUS_INVALID_PARAMETER 0xc000000du
#define STATUS_PROCESS_IS_TERMINATING 0xc000010au
#define STATUS_DEVICE_BUSY 0x80000011u
#define STATUS_TIMEOUT 258u
#define STATUS_NO_MEMORY 0xc0000017u
#define STATUS_RETRY 0xc000022du
#define STATUS_SUCCESS 0u
struct process { unsigned id; struct list thread_list; };
struct thread { unsigned id; struct list proc_entry; };
static struct process proc = {.id = 24};
static struct thread first = {.id = 28}, second = {.id = 32};
static void enum_processes(int (*visit)(struct process *, void *), void *ctx) { visit(&proc, ctx); }
static void ios_wineserver_wake(void) {}
#include "../../build/wineserver/checkpoint_server.inc"
#include "../../build/win32u-unix/checkpoint_message.h"
#define STATUS_UNSUCCESSFUL 0xc0000001u
static _Thread_local struct { struct { uint32_t UniqueThread; } ClientId; } teb;
#define NtCurrentTeb() (&teb)
#define HandleToULong(x) (x)
struct ios_message_wait { uint32_t handle; };
unsigned int ios_checkpoint_capture_message_wait(const struct ios_message_wait *frame, uint32_t tid,
                                                struct ios_checkpoint_message_wait *record)
{
    *record = (struct ios_checkpoint_message_wait){.tid = tid, .handles = {frame->handle}};
    return STATUS_SUCCESS;
}
#include "../../build/win32u-unix/checkpoint_message_hold.inc"
#include "../../build/win32u-unix/checkpoint_session.inc"

static struct ios_checkpoint_roster roster;
static unsigned int result, calls;
static pthread_t owner;
static int parked_visits;
static unsigned int inspect_session(const struct ios_checkpoint_roster *r,
    const struct ios_checkpoint_message_wait *records, void *context)
{
    (void)context;
    assert(pthread_equal(owner, pthread_self()));
    assert(r->count == 1 && r->clients[0].pid == proc.id);
    assert(records[0].tid == first.id && records[0].handles[0] == 84);
    ++parked_visits;
    return STATUS_SUCCESS;
}
static void *session(void *unused)
{
    (void)unused;
    result = ios_checkpoint_visit_message_session(5000, inspect_session, NULL);
    return NULL;
}
static void *client(void *unused)
{
    (void)unused;
    teb.ClientId.UniqueThread = first.id;
    while (!__atomic_load_n(&message_hold_epoch, __ATOMIC_ACQUIRE)) sched_yield();
    struct ios_message_wait frame = {.handle = 84};
    checkpoint_before_message_wait(&frame);
    return NULL;
}
static unsigned int visit(void *ctx)
{
    assert(pthread_equal(owner, pthread_self()));
    ++calls;
    return *(unsigned int *)ctx;
}
static void *capture(void *unused)
{
    (void)unused;
    result = ios_checkpoint_get_roster(&roster, 5000);
    return NULL;
}
static void *verify(void *unused)
{
    (void)unused;
    unsigned int marker = 37;
    result = ios_checkpoint_visit_parked(&roster, 5000, visit, &marker);
    return NULL;
}
static pthread_t queue(void *(*call)(void *))
{
    pthread_t caller;
    assert(!pthread_create(&caller, NULL, call, NULL));
    while (!__atomic_load_n(&checkpoint_pending, __ATOMIC_ACQUIRE)) sched_yield();
    return caller;
}
int main(void)
{
    owner = pthread_self();
    list_init(&proc.thread_list);
    list_add_tail(&proc.thread_list, &first.proc_entry);
    assert(ios_checkpoint_get_roster(&roster, 5) == STATUS_PROCESS_IS_TERMINATING);
    checkpoint_server_start();
    assert(ios_checkpoint_get_roster(&roster, 5) == STATUS_TIMEOUT);
    checkpoint_server_dispatch();
    pthread_t caller = queue(capture);
    assert(ios_checkpoint_get_roster(&roster, 5) == STATUS_DEVICE_BUSY);
    checkpoint_server_dispatch();
    assert(!pthread_join(caller, NULL) && !result);
    assert(roster.count == 1 && roster.clients[0].tid == 28 && roster.clients[0].pid == 24);
    caller = queue(verify);
    list_add_tail(&proc.thread_list, &second.proc_entry);
    checkpoint_server_dispatch();
    assert(!pthread_join(caller, NULL) && result == STATUS_RETRY && !calls);
    list_remove(&second.proc_entry);
    caller = queue(verify);
    checkpoint_server_dispatch();
    assert(!pthread_join(caller, NULL) && result == 37 && calls == 1);
    caller = queue(verify);
    checkpoint_server_stop();
    assert(!pthread_join(caller, NULL) && result == STATUS_PROCESS_IS_TERMINATING);
    checkpoint_server_start();
    verify(NULL);
    assert(result == STATUS_PROCESS_IS_TERMINATING && calls == 1);
    free(roster.clients);
    for (int change = 0; change < 2; ++change)
    {
        pthread_t worker;
        assert(!pthread_create(&worker, NULL, client, NULL));
        caller = queue(session);
        checkpoint_server_dispatch();
        while (!__atomic_load_n(&checkpoint_pending, __ATOMIC_ACQUIRE)) sched_yield();
        if (change) list_add_tail(&proc.thread_list, &second.proc_entry);
        checkpoint_server_dispatch();
        assert(!pthread_join(caller, NULL) && !pthread_join(worker, NULL));
        assert(parked_visits == 1 && result == (change ? STATUS_RETRY : STATUS_SUCCESS));
    }
    puts("PASS owner-thread capture, roster churn, timeout, shutdown and stale session");
}
