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
    uint64_t out_of_order,thread_overflow,bytes,instance_overflow,generation_overflow;
    uint64_t buffer_count,buffer_overflow,buffer_dropped,started_ticks;
    uint64_t unknown[SR_UNKNOWNS];
    struct sr_metric stages[SR_STAGES],total;
    struct sr_frontend frontend;
    struct sr_instance instances[SR_INSTANCES];
    struct sr_generation generations[SR_GENERATIONS];
    struct sr_buffer_event buffers[SR_BUFFER_EVENTS];
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
        .bytes=b->fingerprint_bytes,.instance_overflow=b->instance_overflow,.generation_overflow=b->generation_overflow,
        .buffer_count=b->buffer_count,.buffer_overflow=b->buffer_overflow,
        .buffer_dropped=__atomic_load_n(&b->buffer_dropped,__ATOMIC_RELAXED)-b->buffer_dropped_base,.started_ticks=b->started_ticks,.total=b->total};
    r->frontend=b->frontend;
    memcpy(r->unknown,b->unknown,sizeof(r->unknown));
    memcpy(r->stages,b->stages,sizeof(r->stages));
    memcpy(r->instances,b->instances,sizeof(r->instances));
    memcpy(r->generations,b->generations,sizeof(r->generations));
    memcpy(r->buffers,b->buffers,sizeof(r->buffers));
    memcpy(r->kind,b->kind,sizeof(r->kind));memcpy(r->outcome,b->outcome,sizeof(r->outcome));
    memcpy(r->threads,b->threads,sizeof(r->threads));sr_unlock(b);return 1;
}
static uint64_t cr_thread_count(const struct sr_thread *t) {
    uint64_t n=0;for(unsigned i=0;i<SR_OUTCOMES;i++)n+=t->outcome[i];return n;
}
/* One compact row per scope; stage values are total/max wall milliseconds.
 * All stages are exclusive, including other; all completed outcomes are included. */
static void cr_stages(uint64_t epoch,double elapsed,double scale,const char *scope,uint64_t instance,unsigned tid,
                      const struct sr_metric *stages,const struct sr_metric *total) {
    dprintf(2,"[steam-compile-time] session=%llu t+%.3f scope=%s instance=%llu tid=%04x completed=%llu total_wall_ms=%.6f max_wall_ms=%.6f "
        "other_ms=%.6f/%.6f decode_ir_ms=%.6f/%.6f recheck_ms=%.6f/%.6f backend_ms=%.6f/%.6f "
        "buffer_lock_wait_ms=%.6f/%.6f lookup_lock_wait_ms=%.6f/%.6f output_ms=%.6f/%.6f exclusive=1 outcomes=all cumulative=1\n",
        (unsigned long long)epoch,elapsed,scope,(unsigned long long)instance,tid,(unsigned long long)total->count,total->ticks*scale,total->max_ticks*scale,
        stages[0].ticks*scale,stages[0].max_ticks*scale,stages[1].ticks*scale,stages[1].max_ticks*scale,
        stages[2].ticks*scale,stages[2].max_ticks*scale,stages[3].ticks*scale,stages[3].max_ticks*scale,
        stages[4].ticks*scale,stages[4].max_ticks*scale,stages[5].ticks*scale,stages[5].max_ticks*scale,
        stages[6].ticks*scale,stages[6].max_ticks*scale);
}
static void cr_unknown(uint64_t epoch,double elapsed,const char *scope,uint64_t instance,unsigned tid,const uint64_t *u) {
    dprintf(2,"[steam-compile-unknown] session=%llu t+%.3f scope=%s instance=%llu tid=%04x history_full=%llu shape_changed=%llu "
        "missing_fingerprint=%llu missing_generation=%llu out_of_order=%llu instance_overflow=%llu cumulative=1\n",
        (unsigned long long)epoch,elapsed,scope,(unsigned long long)instance,tid,
        (unsigned long long)u[0],(unsigned long long)u[1],(unsigned long long)u[2],
        (unsigned long long)u[3],(unsigned long long)u[4],(unsigned long long)u[5]);
}
static void cr_classes(uint64_t epoch,double elapsed,double scale,const char *scope,uint64_t instance,
                       uint64_t owner,uint64_t generation,const struct sr_metric *kind) {
    dprintf(2,"[steam-compile-classes] session=%llu t+%.3f scope=%s instance=%llu owner=%llu generation=%llu "
        "first_observed=%llu changed_content=%llu same_content_new_generation=%llu same_content_same_generation=%llu unknown=%llu "
        "first_wall_ms=%.6f changed_wall_ms=%.6f new_generation_wall_ms=%.6f same_generation_wall_ms=%.6f unknown_wall_ms=%.6f cumulative=1\n",
        (unsigned long long)epoch,elapsed,scope,(unsigned long long)instance,(unsigned long long)owner,(unsigned long long)generation,
        (unsigned long long)kind[0].count,(unsigned long long)kind[1].count,(unsigned long long)kind[2].count,
        (unsigned long long)kind[3].count,(unsigned long long)kind[4].count,
        kind[0].ticks*scale,kind[1].ticks*scale,kind[2].ticks*scale,kind[3].ticks*scale,kind[4].ticks*scale);
}
/* Nested timings: phases partition decode_ir, passes are children of pass-manager.
 * Work is total/max/samples. SSA slots are O(1) list storage size, not live nodes. */
static void cr_frontend(uint64_t epoch,double elapsed,double scale,const char *scope,uint64_t instance,unsigned tid,
                        const struct sr_frontend *f,const struct sr_metric *parent) {
    if(!f->calls)return;
    uint64_t accounted=0,pass_ticks=0;
    for(unsigned i=0;i<SR_IR_PHASES;i++)accounted+=f->phases[i].ticks;
    for(unsigned i=0;i<SR_IR_PASSES_COUNT;i++)pass_ticks+=f->passes[i].ticks;
    dprintf(2,"[steam-compile-ir] session=%llu t+%.3f scope=%s instance=%llu tid=%04x calls=%llu returned=%llu custom=%llu "
        "decode_ir_ms=%.6f accounted_ms=%.6f parent_ticks=%llu accounted_ticks=%llu "
        "other_ms=%.6f/%.6f/%llu setup_ms=%.6f/%.6f/%llu decode_ms=%.6f/%.6f/%llu "
        "build_ms=%.6f/%.6f/%llu finalize_ms=%.6f/%.6f/%llu pass_manager_ms=%.6f/%.6f/%llu "
        "pass_sum_ms=%.6f fingerprint_in=build format=total-max-visits outcomes=all cumulative=1\n",
        (unsigned long long)epoch,elapsed,scope,(unsigned long long)instance,tid,
        (unsigned long long)f->calls,(unsigned long long)f->returned,(unsigned long long)f->custom,
        parent->ticks*scale,accounted*scale,(unsigned long long)parent->ticks,(unsigned long long)accounted,
        f->phases[0].ticks*scale,f->phases[0].max_ticks*scale,(unsigned long long)f->phases[0].count,
        f->phases[1].ticks*scale,f->phases[1].max_ticks*scale,(unsigned long long)f->phases[1].count,
        f->phases[2].ticks*scale,f->phases[2].max_ticks*scale,(unsigned long long)f->phases[2].count,
        f->phases[3].ticks*scale,f->phases[3].max_ticks*scale,(unsigned long long)f->phases[3].count,
        f->phases[4].ticks*scale,f->phases[4].max_ticks*scale,(unsigned long long)f->phases[4].count,
        f->phases[5].ticks*scale,f->phases[5].max_ticks*scale,(unsigned long long)f->phases[5].count,pass_ticks*scale);
#define CR_WORK(w) (unsigned long long)(w).total,(unsigned long long)(w).max,(unsigned long long)(w).count
    dprintf(2,"[steam-compile-ir-work] session=%llu t+%.3f scope=%s instance=%llu tid=%04x "
        "decoded_instructions=%llu/%llu/%llu decoded_blocks=%llu/%llu/%llu emitted_instructions=%llu/%llu/%llu "
        "ssa_before=%llu/%llu/%llu ssa_after=%llu/%llu/%llu format=total-max-samples ssa=allocated-slots cumulative=1\n",
        (unsigned long long)epoch,elapsed,scope,(unsigned long long)instance,tid,
        CR_WORK(f->decoded_instructions),CR_WORK(f->decoded_blocks),CR_WORK(f->emitted_instructions),
        CR_WORK(f->ssa_before),CR_WORK(f->ssa_after));
    static const char *names[SR_IR_PASSES_COUNT]={"other","x87-stack","dead-flags","register-allocation","validation","ir-dump"};
    for(unsigned i=0;i<SR_IR_PASSES_COUNT;i++) {
        const struct sr_metric *m=&f->passes[i];if(!m->count)continue;
        dprintf(2,"[steam-compile-ir-pass] session=%llu t+%.3f scope=%s instance=%llu tid=%04x pass=%s calls=%llu "
            "total_wall_ms=%.6f mean_wall_ms=%.6f max_wall_ms=%.6f ssa_in=%llu/%llu/%llu ssa_out=%llu/%llu/%llu "
            "parent=pass_manager work_format=total-max-samples cumulative=1\n",
            (unsigned long long)epoch,elapsed,scope,(unsigned long long)instance,tid,names[i],(unsigned long long)m->count,
            m->ticks*scale,m->ticks*scale/m->count,m->max_ticks*scale,CR_WORK(f->pass_ssa_in[i]),CR_WORK(f->pass_ssa_out[i]));
    }
    const struct sr_ra *ra=&f->ra;
    if(ra->eligible) {
        uint64_t ra_accounted=0;for(unsigned i=0;i<SR_RA_PHASES;i++)ra_accounted+=ra->phases[i].ticks;
        dprintf(2,"[steam-compile-ra] session=%llu t+%.3f scope=%s instance=%llu tid=%04x eligible=%llu samples=%llu returned=%llu "
            "stride=%u total_wall_ms=%.6f max_wall_ms=%.6f parent_ticks=%llu accounted_ticks=%llu "
            "setup_ms=%.6f/%.6f check_ms=%.6f/%.6f reverse_ms=%.6f/%.6f forward_ms=%.6f/%.6f cleanup_ms=%.6f/%.6f "
            "format=total-max-per-sampled-call sampled-only=1 parent=register-allocation cumulative=1\n",
            (unsigned long long)epoch,elapsed,scope,(unsigned long long)instance,tid,
            (unsigned long long)ra->eligible,(unsigned long long)ra->sampled,(unsigned long long)ra->returned,SR_RA_STRIDE,
            ra->total.ticks*scale,ra->total.max_ticks*scale,(unsigned long long)ra->total.ticks,(unsigned long long)ra_accounted,
            ra->phases[0].ticks*scale,ra->phases[0].max_ticks*scale,ra->phases[1].ticks*scale,ra->phases[1].max_ticks*scale,
            ra->phases[2].ticks*scale,ra->phases[2].max_ticks*scale,ra->phases[3].ticks*scale,ra->phases[3].max_ticks*scale,
            ra->phases[4].ticks*scale,ra->phases[4].max_ticks*scale);
        dprintf(2,"[steam-compile-ra-work] session=%llu t+%.3f scope=%s instance=%llu tid=%04x "
            "ssa_slots=%llu/%llu/%llu blocks=%llu/%llu/%llu reverse_nodes=%llu/%llu/%llu "
            "forward_nodes=%llu/%llu/%llu suspect_blocks=%llu/%llu/%llu "
            "format=total-max-samples sampled-only=1 reverse-and-forward-may-differ=1 cumulative=1\n",
            (unsigned long long)epoch,elapsed,scope,(unsigned long long)instance,tid,
            CR_WORK(ra->slots),CR_WORK(ra->blocks),CR_WORK(ra->reverse_nodes),CR_WORK(ra->forward_nodes),CR_WORK(ra->suspect_blocks));
        dprintf(2,"[steam-compile-ra-detail] session=%llu t+%.3f scope=%s instance=%llu tid=%04x samples=%llu "
            "spilled_blocks=%llu/%llu/%llu spill_requests=%llu/%llu/%llu spills=%llu/%llu/%llu "
            "fill_requests=%llu/%llu/%llu fills=%llu/%llu/%llu remats=%llu/%llu/%llu "
            "next_use_nodes=%llu/%llu/%llu merge_attempts=%llu/%llu/%llu merge_successes=%llu/%llu/%llu "
            "format=total-max-samples sampled-only=1 spill-fill=emitted-IR cumulative=1\n",
            (unsigned long long)epoch,elapsed,scope,(unsigned long long)instance,tid,(unsigned long long)ra->sampled,
            CR_WORK(ra->spilled_blocks),CR_WORK(ra->spill_requests),CR_WORK(ra->spills),
            CR_WORK(ra->fill_requests),CR_WORK(ra->fills),CR_WORK(ra->remats),
            CR_WORK(ra->next_use_nodes),CR_WORK(ra->merge_attempts),CR_WORK(ra->merge_successes));
        dprintf(2,"[steam-compile-ra-next-use] session=%llu t+%.3f scope=%s instance=%llu tid=%04x "
            "calls=%llu returned=%llu total_wall_ms=%.6f mean_wall_ms=%.6f max_wall_ms=%.6f "
            "parent=forward sampled-only=1 max=per-scan nodes=inspected-including-until cumulative=1\n",
            (unsigned long long)epoch,elapsed,scope,(unsigned long long)instance,tid,
            (unsigned long long)ra->next_uses.count,(unsigned long long)ra->next_use_returned,
            ra->next_uses.ticks*scale,ra->next_uses.count?ra->next_uses.ticks*scale/ra->next_uses.count:0,
            ra->next_uses.max_ticks*scale);
    }
#undef CR_WORK
}
static void cr_report(uint64_t epoch,uint64_t started,uint64_t begun_start,uint64_t dropped_start,const char *reason) {
    struct sr_bridge *b=cr_bridge;struct cr_report *r;
    if(!b||atomic_load(&cr_epoch)!=epoch)return;
    r=malloc(sizeof(*r));
    if(!r){dprintf(2,"[steam-compile-reason] session=%llu snapshot=storage-unavailable\n",(unsigned long long)epoch);return;}
    double elapsed=(cr_now()-started)/1e9;
    if(!cr_snapshot(b,epoch,r)) {
        dprintf(2,"[steam-compile-reason] session=%llu t+%.3f reason=%s snapshot=busy cumulative=1\n",
                (unsigned long long)epoch,elapsed,reason);free(r);return;
    }
    double scale=1000.0/b->frequency;
    static const char *names[SR_KINDS]={"first-observed","changed-content","same-content-new-generation","same-content-same-generation","unknown"};
    dprintf(2,"[steam-compile-reason] session=%llu t+%.3f reason=%s attached_paths=%llu begun=%llu completed=%llu generated=%llu raced=%llu failed=%llu delivery=%llu "
        "first_observed=%llu changed_content=%llu same_content_new_generation=%llu same_content_same_generation=%llu unknown=%llu "
        "history_used=%llu history_capacity=%u history_full=%llu shape_changed=%llu missing_fingerprint=%llu missing_generation=%llu out_of_order=%llu "
        "dropped=%llu thread_overflow=%llu fingerprint_bytes=%llu instance_overflow=%llu generation_overflow=%llu buffer_events=%llu buffer_overflow=%llu buffer_dropped=%llu coverage=observed-window identity=PE-instance-owner-rip-mode hash=128bit causality=unproven cumulative=1\n",
        (unsigned long long)epoch,elapsed,reason,(unsigned long long)__atomic_load_n(&b->attached,__ATOMIC_RELAXED),
        (unsigned long long)(__atomic_load_n(&b->begun,__ATOMIC_RELAXED)-begun_start),(unsigned long long)r->attempts,
        (unsigned long long)r->outcome[SR_GENERATED],(unsigned long long)r->outcome[SR_RACED],(unsigned long long)r->outcome[SR_FAILED],(unsigned long long)r->outcome[SR_DELIVERY],
        (unsigned long long)r->kind[SR_FIRST].count,(unsigned long long)r->kind[SR_CHANGED].count,(unsigned long long)r->kind[SR_NEW_GENERATION].count,
        (unsigned long long)r->kind[SR_SAME_GENERATION].count,(unsigned long long)r->kind[SR_UNKNOWN].count,
        (unsigned long long)r->history_used,SR_HISTORY,(unsigned long long)r->history_full,(unsigned long long)r->shape_changed,
        (unsigned long long)r->missing_fingerprint,(unsigned long long)r->missing_generation,(unsigned long long)r->out_of_order,
        (unsigned long long)(__atomic_load_n(&b->dropped,__ATOMIC_RELAXED)-dropped_start),(unsigned long long)r->thread_overflow,(unsigned long long)r->bytes,
        (unsigned long long)r->instance_overflow,(unsigned long long)r->generation_overflow,(unsigned long long)r->buffer_count,
        (unsigned long long)r->buffer_overflow,(unsigned long long)r->buffer_dropped);
    for(unsigned i=0;i<SR_KINDS;i++) {
        struct sr_metric *m=&r->kind[i];
        dprintf(2,"[steam-compile-kind] session=%llu t+%.3f kind=%s count=%llu total_wall_ms=%.6f mean_wall_ms=%.6f max_wall_ms=%.6f scope=decode-through-backend wall-not-CPU=1 cumulative=1\n",
            (unsigned long long)epoch,elapsed,names[i],(unsigned long long)m->count,m->ticks*scale,m->count?m->ticks*scale/m->count:0,m->max_ticks*scale);
    }
    cr_stages(epoch,elapsed,scale,"global",0,0,r->stages,&r->total);
    cr_frontend(epoch,elapsed,scale,"global",0,0,&r->frontend,&r->stages[SR_DECODE_IR]);
    cr_unknown(epoch,elapsed,"global",0,0,r->unknown);
    for(unsigned i=0;i<SR_INSTANCES;i++) {
        const struct sr_instance *t=&r->instances[i];if(t->epoch!=epoch)continue;
        dprintf(2,"[steam-compile-instance] session=%llu t+%.3f instance=%llu pid=%04x path=%s target=%s history_used=%llu history_capacity=%u "
            "probe_exhausted=%llu capacity_exhausted=%llu generated=%llu raced=%llu failed=%llu delivery=%llu cumulative=1\n",
            (unsigned long long)epoch,elapsed,(unsigned long long)t->instance,t->pid,t->path==1?"wow64":"arm64ec",t->cef?"cef":"ordinary",
            (unsigned long long)t->history_used,t->capacity,(unsigned long long)t->probe_exhausted,(unsigned long long)t->capacity_exhausted,
            (unsigned long long)t->outcome[0],(unsigned long long)t->outcome[1],(unsigned long long)t->outcome[2],(unsigned long long)t->outcome[3]);
        cr_classes(epoch,elapsed,scale,"instance",t->instance,0,0,t->kind);
        cr_unknown(epoch,elapsed,"instance",t->instance,0,t->unknown);
        cr_stages(epoch,elapsed,scale,"instance",t->instance,0,t->stages,&t->total);
        cr_frontend(epoch,elapsed,scale,"instance",t->instance,0,&t->frontend,&t->stages[SR_DECODE_IR]);
    }
    for(unsigned i=0;i<SR_GENERATIONS;i++) {
        const struct sr_generation *g=&r->generations[i];if(g->epoch!=epoch)continue;
        dprintf(2,"[steam-compile-generation] session=%llu t+%.3f instance=%llu owner=%llu generation=%llu rx=0x%llx used_high_water=%llu capacity=%llu cumulative=1\n",
            (unsigned long long)epoch,elapsed,(unsigned long long)g->instance,(unsigned long long)g->owner,(unsigned long long)g->generation,
            (unsigned long long)g->output.rx,(unsigned long long)g->output.used,(unsigned long long)g->output.capacity);
        cr_classes(epoch,elapsed,scale,"generation",g->instance,g->owner,g->generation,g->kind);
    }
    static const char *buffer_reasons[]={"initial","capacity","explicit-or-other"};
    for(unsigned i=0;i<r->buffer_count;i++) {
        const struct sr_buffer_event *e=&r->buffers[i];
        double event_time=e->ticks>=r->started_ticks?(e->ticks-r->started_ticks)/(double)b->frequency:0;
        dprintf(2,"[steam-compile-buffer] session=%llu t+%.3f event=%u event_t+%.6f instance=%llu owner=%llu pid=%04x tid=%04x path=%u reason=%s "
            "previous=%llu generation=%llu old_rx=0x%llx old_used=%llu old_capacity=%llu rx=0x%llx capacity=%llu requested=%llu begun_marker=%llu cumulative=1\n",
            (unsigned long long)epoch,elapsed,i+1,event_time,(unsigned long long)e->instance,(unsigned long long)e->owner,e->pid,e->tid,e->path,
            buffer_reasons[e->reason],(unsigned long long)e->previous,(unsigned long long)e->generation,(unsigned long long)e->old_rx,
            (unsigned long long)e->old_used,(unsigned long long)e->old_capacity,(unsigned long long)e->rx,
            (unsigned long long)e->capacity,(unsigned long long)e->requested,(unsigned long long)e->order);
    }
    int printed[SR_THREADS]={0};
    for(unsigned shown=0;shown<8;shown++) {
        int best=-1;
        for(unsigned i=0;i<SR_THREADS;i++)if(!printed[i]&&r->threads[i].epoch==epoch&&cr_thread_count(&r->threads[i])&&
            (best<0||cr_thread_count(&r->threads[i])>cr_thread_count(&r->threads[best])))best=(int)i;
        if(best<0)break;
        printed[best]=1;struct sr_thread *t=&r->threads[best];
        dprintf(2,"[steam-compile-thread] session=%llu t+%.3f instance=%llu path=%s pid=%04x tid=%04x "
            "first_observed=%llu changed_content=%llu same_content_new_generation=%llu same_content_same_generation=%llu unknown=%llu "
            "first_wall_ms=%.6f changed_wall_ms=%.6f new_generation_wall_ms=%.6f same_generation_wall_ms=%.6f unknown_wall_ms=%.6f "
            "generated=%llu raced=%llu failed=%llu delivery=%llu cumulative=1\n",
            (unsigned long long)epoch,elapsed,(unsigned long long)t->instance,t->path==1?"wow64":"arm64ec",t->pid,t->tid,
            (unsigned long long)t->kind[0].count,(unsigned long long)t->kind[1].count,(unsigned long long)t->kind[2].count,
            (unsigned long long)t->kind[3].count,(unsigned long long)t->kind[4].count,
            t->kind[0].ticks*scale,t->kind[1].ticks*scale,t->kind[2].ticks*scale,t->kind[3].ticks*scale,t->kind[4].ticks*scale,
            (unsigned long long)t->outcome[0],(unsigned long long)t->outcome[1],(unsigned long long)t->outcome[2],(unsigned long long)t->outcome[3]);
        cr_unknown(epoch,elapsed,"thread",t->instance,t->tid,t->unknown);
        cr_stages(epoch,elapsed,scale,"thread",t->instance,t->tid,t->stages,&t->total);
        cr_frontend(epoch,elapsed,scale,"thread",t->instance,t->tid,&t->frontend,&t->stages[SR_DECODE_IR]);
    }
    // Retain all recorded CEF frontend threads, even below the legacy top-eight
    // completion ranking. This avoids dropping the renderer during other peaks.
    for(unsigned i=0;i<SR_THREADS;i++) {
        const struct sr_thread *t=&r->threads[i];
        if(!printed[i]&&t->epoch==epoch&&t->cef)
            cr_frontend(epoch,elapsed,scale,"thread",t->instance,t->tid,&t->frontend,&t->stages[SR_DECODE_IR]);
    }
    free(r);
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
            uint64_t attempts=0;
            if(sr_lock(cr_bridge)){attempts=cr_bridge->attempts;sr_unlock(cr_bridge);}
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
    b->instance_overflow=b->generation_overflow=b->buffer_count=b->buffer_overflow=0;
    memset(&b->frontend,0,sizeof(b->frontend));
    memset(b->unknown,0,sizeof(b->unknown));
    __asm__ volatile("isb\nmrs %0, cntvct_el0":"=r"(b->started_ticks)::"memory");
    b->buffer_dropped_base=__atomic_load_n(&b->buffer_dropped,__ATOMIC_RELAXED);
    memset(b->stages,0,sizeof(b->stages));memset(&b->total,0,sizeof(b->total));
    memset(b->kind,0,sizeof(b->kind));memset(b->outcome,0,sizeof(b->outcome));sr_unlock(b);
    if(!cr_timebase.denom)mach_timebase_info(&cr_timebase);
    cr_started=cr_now();
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
        "cef_banks=%u cef_capacity=%u ordinary_banks=%u ordinary_capacity=%u probes=%u "
        "source=decoder-snapshots fingerprint=128bit first=first-observed-in-window classification=observational\n",
        (unsigned long long)epoch,SR_MAX_COMPLETIONS,SR_HISTORY,sizeof(*b),
        SR_CEF_INSTANCES,SR_CEF_HISTORY,SR_ORDINARY_INSTANCES,SR_ORDINARY_HISTORY,SR_PROBES);
done:
    pthread_cond_broadcast(&cr_wake);pthread_mutex_unlock(&cr_control);errno=saved;
}
void ios_steam_compile_log_set_active(int active) {
    atomic_store(&cr_active,!!active);
    if(!active)ios_steam_compile_log_configure(0);
}
