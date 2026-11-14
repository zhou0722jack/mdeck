/* mdeck diagnostic-only shared ABI. No guest memory reads or callbacks. */
#ifndef MDECK_STEAM_COMPILE_REASON_ABI_H
#define MDECK_STEAM_COMPILE_REASON_ABI_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define SR_MAGIC UINT64_C(0x4d4452434d503035)
/* Private banks: ordinary startup can never consume a CEF bank. */
#define SR_ORDINARY_INSTANCES 16
#define SR_CEF_INSTANCES 2
#define SR_INSTANCES (SR_ORDINARY_INSTANCES + SR_CEF_INSTANCES)
#define SR_ORDINARY_HISTORY 8192
#define SR_CEF_HISTORY 524288
#define SR_HISTORY (SR_ORDINARY_INSTANCES * SR_ORDINARY_HISTORY + SR_CEF_INSTANCES * SR_CEF_HISTORY)
#define SR_THREADS 128
#define SR_PROBES 32
#define SR_GENERATIONS 128
#define SR_BUFFER_EVENTS 128
#define SR_MAX_BYTES 16384
#define SR_MAX_INSTRUCTIONS 2048
#define SR_MAX_COMPLETIONS 400000
enum sr_kind { SR_FIRST, SR_CHANGED, SR_NEW_GENERATION, SR_SAME_GENERATION, SR_UNKNOWN, SR_KINDS };
enum sr_outcome { SR_GENERATED, SR_RACED, SR_FAILED, SR_DELIVERY, SR_OUTCOMES };
enum sr_unknown { SR_HISTORY_FULL, SR_SHAPE_CHANGED, SR_MISSING_FINGERPRINT, SR_MISSING_GENERATION,
                  SR_OUT_OF_ORDER, SR_INSTANCE_OVERFLOW, SR_UNKNOWNS };
enum sr_stage { SR_OTHER, SR_DECODE_IR, SR_RECHECK, SR_BACKEND, SR_BUFFER_WAIT, SR_LOOKUP_WAIT, SR_OUTPUT, SR_STAGES };
/* Stable IDs shared by PE producers and the native logger. Unknown/custom
 * passes remain visible in OTHER; no RTTI, dynamic names or IR walks. */
enum sr_ir_phase { SR_IR_OTHER, SR_IR_SETUP, SR_IR_DECODE, SR_IR_BUILD, SR_IR_FINALIZE, SR_IR_PASSES, SR_IR_PHASES };
enum sr_ir_pass { SR_PASS_OTHER, SR_PASS_X87, SR_PASS_DFE, SR_PASS_RA, SR_PASS_VALIDATE, SR_PASS_DUMP, SR_IR_PASSES_COUNT };
#define SR_RA_STRIDE 64
enum sr_ra_phase { SR_RA_SETUP, SR_RA_CHECK, SR_RA_REVERSE, SR_RA_FORWARD, SR_RA_CLEANUP, SR_RA_PHASES };
enum sr_buffer_reason { SR_BUFFER_INITIAL, SR_BUFFER_CAPACITY, SR_BUFFER_EXPLICIT };
struct sr_fingerprint {
    uint64_t shape, content_a, content_b, bytes, instructions;
    unsigned invalid;
};
static inline struct sr_fingerprint sr_fingerprint_init(void) {
    struct sr_fingerprint f = {0,0,0,0,0,0};
    f.shape = UINT64_C(14695981039346656037);
    f.content_a = UINT64_C(14695981039346656037);
    f.content_b = UINT64_C(0x9e3779b97f4a7c15);
    return f;
}
static inline void sr_hash_word(uint64_t *hash, uint64_t word) {
    for (unsigned i=0;i<8;i++) { *hash=(*hash^(uint8_t)word)*UINT64_C(1099511628211);word>>=8; }
}
/* Input is the decoder's InstBytes snapshot, never a second guest read.
 * Layout is separate: a different instruction/block shape is not evidence
 * of changed guest bytes. Include the boundaries of decoded basic blocks. */
static inline void sr_fingerprint_block(struct sr_fingerprint *f, uint64_t address) {
    if (f->invalid) return;
    sr_hash_word(&f->shape, UINT64_MAX);sr_hash_word(&f->shape,address);
}
static inline void sr_fingerprint_inst(struct sr_fingerprint *f, uint64_t address,
                                      const uint8_t *bytes, unsigned count) {
    if (f->invalid) return;
    if (!bytes || !count || count>15 || f->instructions>=SR_MAX_INSTRUCTIONS ||
        f->bytes>SR_MAX_BYTES-count || address>UINT64_MAX-count) { f->invalid=1;return; }
    sr_hash_word(&f->shape,address);sr_hash_word(&f->shape,count);
    for (unsigned i=0;i<count;i++) {
        f->content_a=(f->content_a^bytes[i])*UINT64_C(1099511628211);
        f->content_b^=(uint64_t)bytes[i]+UINT64_C(0x9e3779b97f4a7c15);
        f->content_b=(f->content_b<<27)|(f->content_b>>37);
        f->content_b*=UINT64_C(0x94d049bb133111eb);
    }
    f->bytes+=count;f->instructions++;
}
struct sr_key { uint64_t instance, owner, rip, max_inst, mode; };
struct sr_history {
    uint64_t epoch;
    struct sr_key key;
    struct sr_fingerprint fingerprint;
    uint64_t generation, order;
};
struct sr_metric { uint64_t count, ticks, max_ticks; };
struct sr_work { uint64_t count, total, max; };
/* RA phase totals cover sampled invocations only, never extrapolated. */
struct sr_ra {
    uint64_t eligible, sampled, returned;
    struct sr_metric total, phases[SR_RA_PHASES];
    struct sr_work slots, blocks, reverse_nodes, forward_nodes, suspect_blocks;
    struct sr_work spilled_blocks, spill_requests, spills, fill_requests, fills, remats;
    struct sr_work next_use_nodes, merge_attempts, merge_successes;
    struct sr_metric next_uses; /* Nested in forward, per entered scan, including partial exits. */
    uint64_t next_use_returned;
};
struct sr_ra_sample {
    uint64_t ticks[SR_RA_PHASES], total, slots, blocks, reverse_nodes, forward_nodes, suspect_blocks;
    uint64_t spilled_blocks, spill_requests, spills, fill_requests, fills, remats;
    uint64_t next_use_nodes, merge_attempts, merge_successes, next_use_returned;
    struct sr_metric next_uses;
    unsigned returned;
};
struct sr_frontend {
    uint64_t calls, returned, custom;
    struct sr_ra ra;
    struct sr_metric phases[SR_IR_PHASES], passes[SR_IR_PASSES_COUNT];
    struct sr_work decoded_instructions, decoded_blocks, emitted_instructions, ssa_before, ssa_after;
    struct sr_work pass_ssa_in[SR_IR_PASSES_COUNT], pass_ssa_out[SR_IR_PASSES_COUNT];
};
struct sr_timing { uint64_t ticks[SR_STAGES]; };
struct sr_output { uint64_t rx, used, capacity; };
struct sr_instance {
    uint64_t epoch, instance;
    unsigned pid, path, cef, offset, capacity;
    uint64_t history_used, probe_exhausted, capacity_exhausted;
    uint64_t unknown[SR_UNKNOWNS], outcome[SR_OUTCOMES];
    struct sr_metric kind[SR_KINDS], stages[SR_STAGES], total;
    struct sr_frontend frontend;
};
struct sr_thread {
    uint64_t epoch, instance;
    unsigned pid, tid, path, cef;
    struct sr_metric kind[SR_KINDS];
    uint64_t outcome[SR_OUTCOMES], unknown[SR_UNKNOWNS];
    struct sr_metric stages[SR_STAGES], total;
    struct sr_frontend frontend;
};
struct sr_generation {
    uint64_t epoch, instance, owner, generation;
    struct sr_output output;
    struct sr_metric kind[SR_KINDS];
};
struct sr_buffer_event {
    uint64_t epoch, instance, owner, ticks, order;
    unsigned pid, tid, path, reason;
    uint64_t previous, generation, old_rx, old_used, old_capacity, rx, capacity, requested;
};
struct sr_bridge {
    uint64_t magic, bytes, frequency, active_epoch, gate, next_instance, attached;
    uint64_t begun, attempts, dropped, classified, fingerprint_bytes;
    uint64_t history_used, history_full, shape_changed, missing_fingerprint, missing_generation;
    uint64_t out_of_order, thread_overflow, instance_overflow, generation_overflow;
    uint64_t buffer_count, buffer_overflow, buffer_dropped, buffer_dropped_base, started_ticks;
    uint64_t unknown[SR_UNKNOWNS];
    struct sr_metric stages[SR_STAGES], total;
    struct sr_frontend frontend;
    struct sr_metric kind[SR_KINDS];
    uint64_t outcome[SR_OUTCOMES];
    struct sr_thread threads[SR_THREADS];
    struct sr_instance instances[SR_INSTANCES];
    struct sr_generation generations[SR_GENERATIONS];
    struct sr_buffer_event buffers[SR_BUFFER_EVENTS];
    struct sr_history history[SR_HISTORY];
};
struct sr_ticket { uint64_t epoch, instance, order; unsigned pid, tid, path, cef; };
static inline int sr_lock(struct sr_bridge *b) {
    uint64_t zero=0;
    return __atomic_compare_exchange_n(&b->gate,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static inline void sr_unlock(struct sr_bridge *b) { __atomic_store_n(&b->gate,0,__ATOMIC_RELEASE); }
static inline uint64_t sr_mix(uint64_t n) {
    n^=n>>30;n*=UINT64_C(0xbf58476d1ce4e5b9);n^=n>>27;n*=UINT64_C(0x94d049bb133111eb);return n^(n>>31);
}
static inline uint64_t sr_hash_key(struct sr_key k) {
    return sr_mix(k.instance^sr_mix(k.owner)^sr_mix(k.rip)^sr_mix(k.max_inst)^k.mode);
}
static inline unsigned sr_probe(struct sr_key k,unsigned capacity,unsigned j) {
    uint64_t hash=sr_hash_key(k);
    /* Odd step visits distinct slots in a power-of-two bank, avoiding primary clustering. */
    return ((unsigned)hash+j*((unsigned)(hash>>32)|1u))&(capacity-1);
}
static inline struct sr_instance *sr_instance_for(struct sr_bridge *b,struct sr_ticket t) {
    unsigned first=t.cef?SR_ORDINARY_INSTANCES:0;
    unsigned end=t.cef?SR_INSTANCES:SR_ORDINARY_INSTANCES;
    for(unsigned i=first;i<end;i++) {
        struct sr_instance *s=&b->instances[i];
        if(s->epoch!=t.epoch) {
            memset(s,0,sizeof(*s));s->epoch=t.epoch;s->instance=t.instance;
            s->pid=t.pid;s->path=t.path;s->cef=t.cef;
            s->capacity=t.cef?SR_CEF_HISTORY:SR_ORDINARY_HISTORY;
            s->offset=t.cef?SR_ORDINARY_INSTANCES*SR_ORDINARY_HISTORY+(i-first)*SR_CEF_HISTORY:i*SR_ORDINARY_HISTORY;
            return s;
        }
        if(s->instance==t.instance)return s;
    }
    return 0;
}
static inline int sr_key_equal(struct sr_key a,struct sr_key b) {
    return a.instance==b.instance&&a.owner==b.owner&&a.rip==b.rip&&a.max_inst==b.max_inst&&a.mode==b.mode;
}
static inline enum sr_kind sr_classify(struct sr_bridge *b,struct sr_instance *s,struct sr_ticket t,struct sr_key key,
                                      struct sr_fingerprint f,uint64_t generation,unsigned *why) {
    if(f.invalid||!f.instructions||!f.bytes){b->missing_fingerprint++;*why=SR_MISSING_FINGERPRINT;return SR_UNKNOWN;}
    if(!generation||!key.owner){b->missing_generation++;*why=SR_MISSING_GENERATION;return SR_UNKNOWN;}
    if(!s){*why=SR_INSTANCE_OVERFLOW;return SR_UNKNOWN;}
    const uint64_t hash=sr_hash_key(key);
    const unsigned start=(unsigned)hash,step=(unsigned)(hash>>32)|1u;
    for(unsigned j=0;j<SR_PROBES;j++) {
        struct sr_history *h=&b->history[s->offset+((start+j*step)&(s->capacity-1))];
        if(h->epoch!=t.epoch) {
            *h=(struct sr_history){.epoch=t.epoch,.key=key,.fingerprint=f,.generation=generation,.order=t.order};
            b->history_used++;s->history_used++;return SR_FIRST;
        }
        if(!sr_key_equal(h->key,key))continue;
        /* Late older completions must not overwrite a newer baseline. */
        if(t.order<=h->order){b->out_of_order++;*why=SR_OUT_OF_ORDER;return SR_UNKNOWN;}
        enum sr_kind kind;
        if(f.shape!=h->fingerprint.shape||f.bytes!=h->fingerprint.bytes||f.instructions!=h->fingerprint.instructions) {
            b->shape_changed++;*why=SR_SHAPE_CHANGED;kind=SR_UNKNOWN;
        } else if(f.content_a!=h->fingerprint.content_a||f.content_b!=h->fingerprint.content_b)kind=SR_CHANGED;
        else kind=generation!=h->generation?SR_NEW_GENERATION:SR_SAME_GENERATION;
        h->fingerprint=f;h->generation=generation;h->order=t.order;return kind;
    }
    /* No eviction: overflow must never turn an old address into a first. */
    b->history_full++;*why=SR_HISTORY_FULL;
    if(s->history_used==s->capacity)s->capacity_exhausted++;else s->probe_exhausted++;
    return SR_UNKNOWN;
}
static inline struct sr_ticket sr_begin(struct sr_bridge *b,uint64_t instance,unsigned pid,unsigned tid,unsigned path) {
    struct sr_ticket t={0,0,0,0,0,0,0};
    if(!b||!instance||!pid||!tid)return t;
    t.epoch=__atomic_load_n(&b->active_epoch,__ATOMIC_ACQUIRE);
    if(!t.epoch)return t;
    t.instance=instance;t.pid=pid;t.tid=tid;t.path=path;
    t.order=__atomic_fetch_add(&b->begun,1,__ATOMIC_RELAXED)+1;
    return t;
}
static inline void sr_add(struct sr_metric *m,uint64_t ticks) {
    m->count++;m->ticks+=ticks;if(ticks>m->max_ticks)m->max_ticks=ticks;
}
static inline void sr_add_timing(struct sr_metric *stages,struct sr_metric *total,const struct sr_timing *timing,uint64_t ticks) {
    sr_add(total,ticks);
    for(unsigned i=0;i<SR_STAGES;i++)sr_add(&stages[i],timing->ticks[i]);
}
static inline void sr_work_add(struct sr_work *w,uint64_t n) {
    w->count++;w->total+=n;if(n>w->max)w->max=n;
}
static inline void sr_metric_merge(struct sr_metric *dst,const struct sr_metric *src) {
    dst->count+=src->count;dst->ticks+=src->ticks;if(src->max_ticks>dst->max_ticks)dst->max_ticks=src->max_ticks;
}
static inline void sr_work_merge(struct sr_work *dst,const struct sr_work *src) {
    dst->count+=src->count;dst->total+=src->total;if(src->max>dst->max)dst->max=src->max;
}
static inline void sr_ra_merge(struct sr_ra *dst,const struct sr_ra *src) {
    dst->eligible+=src->eligible;dst->sampled+=src->sampled;dst->returned+=src->returned;
    sr_metric_merge(&dst->total,&src->total);
    for(unsigned i=0;i<SR_RA_PHASES;i++)sr_metric_merge(&dst->phases[i],&src->phases[i]);
    sr_work_merge(&dst->slots,&src->slots);sr_work_merge(&dst->blocks,&src->blocks);
    sr_work_merge(&dst->reverse_nodes,&src->reverse_nodes);sr_work_merge(&dst->forward_nodes,&src->forward_nodes);
    sr_work_merge(&dst->suspect_blocks,&src->suspect_blocks);
    sr_work_merge(&dst->spilled_blocks,&src->spilled_blocks);sr_work_merge(&dst->spill_requests,&src->spill_requests);
    sr_work_merge(&dst->spills,&src->spills);sr_work_merge(&dst->fill_requests,&src->fill_requests);
    sr_work_merge(&dst->fills,&src->fills);sr_work_merge(&dst->remats,&src->remats);
    sr_work_merge(&dst->next_use_nodes,&src->next_use_nodes);
    sr_work_merge(&dst->merge_attempts,&src->merge_attempts);sr_work_merge(&dst->merge_successes,&src->merge_successes);
    sr_metric_merge(&dst->next_uses,&src->next_uses);dst->next_use_returned+=src->next_use_returned;
}
static inline void sr_frontend_merge(struct sr_frontend *dst,const struct sr_frontend *src) {
    if(!src)return;
    sr_ra_merge(&dst->ra,&src->ra);
    dst->calls+=src->calls;dst->returned+=src->returned;dst->custom+=src->custom;
    for(unsigned i=0;i<SR_IR_PHASES;i++)sr_metric_merge(&dst->phases[i],&src->phases[i]);
    for(unsigned i=0;i<SR_IR_PASSES_COUNT;i++) {
        sr_metric_merge(&dst->passes[i],&src->passes[i]);
        sr_work_merge(&dst->pass_ssa_in[i],&src->pass_ssa_in[i]);
        sr_work_merge(&dst->pass_ssa_out[i],&src->pass_ssa_out[i]);
    }
    sr_work_merge(&dst->decoded_instructions,&src->decoded_instructions);
    sr_work_merge(&dst->decoded_blocks,&src->decoded_blocks);
    sr_work_merge(&dst->emitted_instructions,&src->emitted_instructions);
    sr_work_merge(&dst->ssa_before,&src->ssa_before);sr_work_merge(&dst->ssa_after,&src->ssa_after);
}
static inline int sr_finish_full(struct sr_bridge *b,struct sr_ticket t,struct sr_key key,
                            struct sr_fingerprint f,uint64_t generation,unsigned outcome,uint64_t ticks,
                            const struct sr_timing *timing,struct sr_output output,const struct sr_frontend *frontend) {
    if(!b||!t.epoch||outcome>=SR_OUTCOMES||__atomic_load_n(&b->active_epoch,__ATOMIC_ACQUIRE)!=t.epoch)return 0;
    if(!sr_lock(b)){__atomic_fetch_add(&b->dropped,1,__ATOMIC_RELAXED);return 0;}
    if(__atomic_load_n(&b->active_epoch,__ATOMIC_ACQUIRE)!=t.epoch||b->attempts>=SR_MAX_COMPLETIONS){sr_unlock(b);return 0;}
    b->attempts++;b->outcome[outcome]++;
    sr_add_timing(b->stages,&b->total,timing,ticks);
    sr_frontend_merge(&b->frontend,frontend);
    struct sr_instance *instance=sr_instance_for(b,t);
    if(instance){instance->outcome[outcome]++;sr_add_timing(instance->stages,&instance->total,timing,ticks);sr_frontend_merge(&instance->frontend,frontend);}
    else b->instance_overflow++;
    enum sr_kind kind=SR_UNKNOWN;
    unsigned why=SR_UNKNOWNS;
    if(outcome==SR_GENERATED) {
        key.instance=t.instance;kind=sr_classify(b,instance,t,key,f,generation,&why);
        sr_add(&b->kind[kind],ticks);b->classified++;b->fingerprint_bytes+=f.bytes;
        if(why<SR_UNKNOWNS)b->unknown[why]++;
        if(instance){sr_add(&instance->kind[kind],ticks);if(why<SR_UNKNOWNS)instance->unknown[why]++;}
        unsigned i;
        for(i=0;i<SR_GENERATIONS;i++) {
            struct sr_generation *g=&b->generations[i];
            if(g->epoch!=t.epoch) {
                memset(g,0,sizeof(*g));g->epoch=t.epoch;g->instance=t.instance;g->owner=key.owner;g->generation=generation;
            }
            if(g->instance!=t.instance||g->owner!=key.owner||g->generation!=generation)continue;
            sr_add(&g->kind[kind],ticks);
            if(output.used>=g->output.used)g->output=output;
            break;
        }
        if(i==SR_GENERATIONS)b->generation_overflow++;
    }
    unsigned index=(unsigned)sr_mix(t.instance^t.tid)&(SR_THREADS-1);
    struct sr_thread *thread=0;
    for(unsigned j=0;j<SR_THREADS;j++) {
        struct sr_thread *s=&b->threads[(index+j)&(SR_THREADS-1)];
        if(s->epoch!=t.epoch){memset(s,0,sizeof(*s));s->epoch=t.epoch;s->instance=t.instance;s->pid=t.pid;s->tid=t.tid;s->path=t.path;s->cef=t.cef;thread=s;break;}
        if(s->instance==t.instance&&s->tid==t.tid){thread=s;break;}
    }
    if(thread) {
        thread->outcome[outcome]++;sr_add_timing(thread->stages,&thread->total,timing,ticks);
        sr_frontend_merge(&thread->frontend,frontend);
        if(outcome==SR_GENERATED){sr_add(&thread->kind[kind],ticks);if(why<SR_UNKNOWNS)thread->unknown[why]++;}
    } else b->thread_overflow++;
    sr_unlock(b);return 1;
}
static inline int sr_finish_detail(struct sr_bridge *b,struct sr_ticket t,struct sr_key key,
                             struct sr_fingerprint f,uint64_t generation,unsigned outcome,uint64_t ticks,
                             const struct sr_timing *timing,struct sr_output output) {
    return sr_finish_full(b,t,key,f,generation,outcome,ticks,timing,output,0);
}
/* Fixture/API wrapper; production always supplies stages and output metadata. */
static inline int sr_finish(struct sr_bridge *b,struct sr_ticket t,struct sr_key key,
                            struct sr_fingerprint f,uint64_t generation,unsigned outcome,uint64_t ticks) {
    struct sr_timing timing={{0}};timing.ticks[SR_OTHER]=ticks;
    return sr_finish_detail(b,t,key,f,generation,outcome,ticks,&timing,(struct sr_output){0,0,0});
}
static inline void sr_buffer_record(struct sr_bridge *b,struct sr_buffer_event e) {
    if(!b||!e.epoch||__atomic_load_n(&b->active_epoch,__ATOMIC_ACQUIRE)!=e.epoch)return;
    if(!sr_lock(b)){__atomic_fetch_add(&b->buffer_dropped,1,__ATOMIC_RELAXED);return;}
    if(__atomic_load_n(&b->active_epoch,__ATOMIC_ACQUIRE)==e.epoch) {
        if(b->buffer_count<SR_BUFFER_EVENTS)b->buffers[b->buffer_count++]=e;else b->buffer_overflow++;
    }
    sr_unlock(b);
}
#endif
