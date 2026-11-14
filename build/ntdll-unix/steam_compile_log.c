/* Bounded compilation observations, independent of thread PC sampling.
 * Producers hash the decoder's existing byte snapshots. This worker only
 * copies counters under a try-lock, then logs after releasing the gate. */
#include "steam_compile_log.h"
#include "../fex-patches/steam_compile_reason_abi.h"
#include <mach/mach_time.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#include <time.h>
#include <unistd.h>
#include <sys/qos.h>

#define CR_DURATION_NS UINT64_C(45000000000)
static pthread_mutex_t cr_control=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cr_wake=PTHREAD_COND_INITIALIZER;
static struct sr_bridge *cr_bridge;
static atomic_int cr_active;
static _Atomic uint64_t cr_epoch;
static uint64_t cr_started,cr_begun_start,cr_dropped_start;
static int cr_worker_started;
static mach_timebase_info_data_t cr_timebase;

static uint64_t cr_now(void) {
    return (uint64_t)((__uint128_t)mach_absolute_time()*cr_timebase.numer/cr_timebase.denom);
}
struct cr_report {
    uint64_t attempts,classified,history_used,history_full,shape_changed,missing_fingerprint,missing_generation;
    uint64_t out_of_order,thread_overflow,bytes;
    struct sr_metric kind[SR_KINDS];
    uint64_t outcome[SR_OUTCOMES];
    struct sr_thread threads[SR_THREADS];
};
static int cr_snapshot(struct sr_bridge *b,uint64_t epoch,struct cr_report *r) {
    if(!sr_lock(b))return 0;
    if(atomic_load(&cr_epoch)!=epoch){sr_unlock(b);return 0;}
    *r=(struct cr_report){.attempts=b->attempts,.classified=b->classified,.history_used=b->history_used,
        .history_full=b->history_full,.shape_changed=b->shape_changed,.missing_fingerprint=b->missing_fingerprint,
        .missing_generation=b->missing_generation,.out_of_order=b->out_of_order,.thread_overflow=b->thread_overflow,
        .bytes=b->fingerprint_bytes};
    memcpy(r->kind,b->kind,sizeof(r->kind));memcpy(r->outcome,b->outcome,sizeof(r->outcome));
    memcpy(r->threads,b->threads,sizeof(r->threads));sr_unlock(b);return 1;
}
static uint64_t cr_thread_count(const struct sr_thread *t) {
    uint64_t n=0;for(unsigned i=0;i<SR_OUTCOMES;i++)n+=t->outcome[i];return n;
}
static void cr_report(uint64_t epoch,uint64_t started,uint64_t begun_start,uint64_t dropped_start,const char *reason) {
    struct sr_bridge *b=cr_bridge;struct cr_report r;
    if(!b||atomic_load(&cr_epoch)!=epoch)return;
    double elapsed=(cr_now()-started)/1e9;
    if(!cr_snapshot(b,epoch,&r)) {
        dprintf(2,"[steam-compile-reason] session=%llu t+%.3f reason=%s snapshot=busy cumulative=1\n",
                (unsigned long long)epoch,elapsed,reason);return;
    }
    double scale=1000.0/b->frequency;
    static const char *names[SR_KINDS]={"first-observed","changed-content","same-content-new-generation","same-content-same-generation","unknown"};
    dprintf(2,"[steam-compile-reason] session=%llu t+%.3f reason=%s attached_paths=%llu begun=%llu completed=%llu generated=%llu raced=%llu failed=%llu delivery=%llu "
        "first_observed=%llu changed_content=%llu same_content_new_generation=%llu same_content_same_generation=%llu unknown=%llu "
        "history_used=%llu history_capacity=%u history_full=%llu shape_changed=%llu missing_fingerprint=%llu missing_generation=%llu out_of_order=%llu "
        "dropped=%llu thread_overflow=%llu fingerprint_bytes=%llu coverage=observed-window identity=PE-instance-owner-rip-mode hash=128bit causality=unproven cumulative=1\n",
        (unsigned long long)epoch,elapsed,reason,(unsigned long long)__atomic_load_n(&b->attached,__ATOMIC_RELAXED),
        (unsigned long long)(__atomic_load_n(&b->begun,__ATOMIC_RELAXED)-begun_start),(unsigned long long)r.attempts,
        (unsigned long long)r.outcome[SR_GENERATED],(unsigned long long)r.outcome[SR_RACED],(unsigned long long)r.outcome[SR_FAILED],(unsigned long long)r.outcome[SR_DELIVERY],
        (unsigned long long)r.kind[SR_FIRST].count,(unsigned long long)r.kind[SR_CHANGED].count,(unsigned long long)r.kind[SR_NEW_GENERATION].count,
        (unsigned long long)r.kind[SR_SAME_GENERATION].count,(unsigned long long)r.kind[SR_UNKNOWN].count,
        (unsigned long long)r.history_used,SR_HISTORY,(unsigned long long)r.history_full,(unsigned long long)r.shape_changed,
        (unsigned long long)r.missing_fingerprint,(unsigned long long)r.missing_generation,(unsigned long long)r.out_of_order,
        (unsigned long long)(__atomic_load_n(&b->dropped,__ATOMIC_RELAXED)-dropped_start),(unsigned long long)r.thread_overflow,(unsigned long long)r.bytes);
    for(unsigned i=0;i<SR_KINDS;i++) {
        struct sr_metric *m=&r.kind[i];
        dprintf(2,"[steam-compile-kind] session=%llu t+%.3f kind=%s count=%llu total_wall_ms=%.6f mean_wall_ms=%.6f max_wall_ms=%.6f scope=decode-through-backend wall-not-CPU=1 cumulative=1\n",
            (unsigned long long)epoch,elapsed,names[i],(unsigned long long)m->count,m->ticks*scale,m->count?m->ticks*scale/m->count:0,m->max_ticks*scale);
    }
    int printed[SR_THREADS]={0};
    for(unsigned shown=0;shown<8;shown++) {
        int best=-1;
        for(unsigned i=0;i<SR_THREADS;i++)if(!printed[i]&&r.threads[i].epoch==epoch&&cr_thread_count(&r.threads[i])&&
            (best<0||cr_thread_count(&r.threads[i])>cr_thread_count(&r.threads[best])))best=(int)i;
        if(best<0)break;
        printed[best]=1;struct sr_thread *t=&r.threads[best];
        dprintf(2,"[steam-compile-thread] session=%llu t+%.3f instance=%llu path=%s pid=%04x tid=%04x "
            "first_observed=%llu changed_content=%llu same_content_new_generation=%llu same_content_same_generation=%llu unknown=%llu "
            "first_wall_ms=%.6f changed_wall_ms=%.6f new_generation_wall_ms=%.6f same_generation_wall_ms=%.6f unknown_wall_ms=%.6f "
            "generated=%llu raced=%llu failed=%llu delivery=%llu cumulative=1\n",
            (unsigned long long)epoch,elapsed,(unsigned long long)t->instance,t->path==1?"wow64":"arm64ec",t->pid,t->tid,
            (unsigned long long)t->kind[0].count,(unsigned long long)t->kind[1].count,(unsigned long long)t->kind[2].count,
            (unsigned long long)t->kind[3].count,(unsigned long long)t->kind[4].count,
            t->kind[0].ticks*scale,t->kind[1].ticks*scale,t->kind[2].ticks*scale,t->kind[3].ticks*scale,t->kind[4].ticks*scale,
            (unsigned long long)t->outcome[0],(unsigned long long)t->outcome[1],(unsigned long long)t->outcome[2],(unsigned long long)t->outcome[3]);
    }
}
static void cr_wait_second(void) {
    struct timespec until;clock_gettime(CLOCK_REALTIME,&until);until.tv_sec++;
    pthread_cond_timedwait(&cr_wake,&cr_control,&until);
}
static const char *cr_stop_reason(uint64_t started,uint64_t now,uint64_t attempts) {
    if(now<started)return "clock-error";
    if(now-started>=CR_DURATION_NS)return "duration-complete";
    if(attempts>=SR_MAX_COMPLETIONS)return "event-budget";
    return NULL;
}
static void *cr_worker(void *unused) {
    (void)unused;pthread_setname_np("mdeck.compile-reasons");pthread_set_qos_class_self_np(QOS_CLASS_UTILITY,0);
    uint64_t handled=0;pthread_mutex_lock(&cr_control);
    for(;;) {
        while(!cr_bridge||atomic_load(&cr_epoch)==handled)pthread_cond_wait(&cr_wake,&cr_control);
        uint64_t epoch=atomic_load(&cr_epoch),started=cr_started;handled=epoch;
        uint64_t begun_start=cr_begun_start,dropped_start=cr_dropped_start;
        pthread_mutex_unlock(&cr_control);
        const char *reason="stopped";
        for(;;) {
            if(__atomic_load_n(&cr_bridge->active_epoch,__ATOMIC_ACQUIRE)!=epoch)break;
            struct cr_report snapshot;
            uint64_t attempts=cr_snapshot(cr_bridge,epoch,&snapshot)?snapshot.attempts:0;
            const char *stop=cr_stop_reason(started,cr_now(),attempts);
            if(stop){reason=stop;break;}
            pthread_mutex_lock(&cr_control);
            if(__atomic_load_n(&cr_bridge->active_epoch,__ATOMIC_ACQUIRE)==epoch)cr_wait_second();
            pthread_mutex_unlock(&cr_control);
            if(atomic_load(&cr_epoch)!=epoch)break;
            cr_report(epoch,started,begun_start,dropped_start,"sampling");
        }
        uint64_t expected=epoch;
        __atomic_compare_exchange_n(&cr_bridge->active_epoch,&expected,0,0,__ATOMIC_RELEASE,__ATOMIC_RELAXED);
        cr_report(epoch,started,begun_start,dropped_start,reason);
        pthread_mutex_lock(&cr_control);
    }
    return NULL;
}
void ios_steam_compile_log_configure(int enabled) {
    int saved=errno;pthread_mutex_lock(&cr_control);
    if(cr_bridge)__atomic_store_n(&cr_bridge->active_epoch,0,__ATOMIC_RELEASE);
    if(!enabled||!atomic_load(&cr_active)) {
        if(!cr_bridge)unsetenv("MADEIRA_COMPILE_REASON_BRIDGE");
        pthread_cond_broadcast(&cr_wake);pthread_mutex_unlock(&cr_control);errno=saved;return;
    }
    uint64_t epoch=atomic_fetch_add(&cr_epoch,1)+1;
    if(!cr_bridge)cr_bridge=calloc(1,sizeof(*cr_bridge));
    if(!cr_bridge){dprintf(2,"[steam-compile-reason] reason=storage-unavailable\n");goto done;}
    struct sr_bridge *b=cr_bridge;
    if(!sr_lock(b)){dprintf(2,"[steam-compile-reason] reason=reset-busy\n");goto done;}
    b->magic=SR_MAGIC;b->bytes=sizeof(*b);
    if(!b->frequency)__asm__ volatile("mrs %0, cntfrq_el0":"=r"(b->frequency));
    b->attempts=b->classified=b->fingerprint_bytes=b->history_used=b->history_full=b->shape_changed=0;
    b->missing_fingerprint=b->missing_generation=b->out_of_order=b->thread_overflow=0;
    memset(b->kind,0,sizeof(b->kind));memset(b->outcome,0,sizeof(b->outcome));sr_unlock(b);
    mach_timebase_info(&cr_timebase);cr_started=cr_now();
    cr_begun_start=__atomic_load_n(&b->begun,__ATOMIC_RELAXED);cr_dropped_start=__atomic_load_n(&b->dropped,__ATOMIC_RELAXED);
    char pointer[32];snprintf(pointer,sizeof(pointer),"%llx",(unsigned long long)(uintptr_t)b);
    if(setenv("MADEIRA_COMPILE_REASON_BRIDGE",pointer,1)){dprintf(2,"[steam-compile-reason] reason=bridge-publish-failed\n");goto done;}
    if(!cr_worker_started) {
        pthread_t thread;int error=pthread_create(&thread,NULL,cr_worker,NULL);
        if(error){dprintf(2,"[steam-compile-reason] reason=worker-create-failed error=%d\n",error);goto done;}
        pthread_detach(thread);cr_worker_started=1;
    }
    __atomic_store_n(&b->active_epoch,epoch,__ATOMIC_RELEASE);
    dprintf(2,"[steam-compile-reason] enabled session=%llu duration=45s interval=1s max_events=%u history_capacity=%u storage_bytes=%zu "
        "source=decoder-snapshots fingerprint=128bit first=first-observed-in-window classification=observational\n",
        (unsigned long long)epoch,SR_MAX_COMPLETIONS,SR_HISTORY,sizeof(*b));
done:
    pthread_cond_broadcast(&cr_wake);pthread_mutex_unlock(&cr_control);errno=saved;
}
void ios_steam_compile_log_set_active(int active) {
    atomic_store(&cr_active,!!active);
    if(!active)ios_steam_compile_log_configure(0);
}
