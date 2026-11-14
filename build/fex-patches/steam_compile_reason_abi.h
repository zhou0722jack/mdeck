/* mdeck diagnostic-only shared ABI. No guest memory reads or callbacks. */
#ifndef MDECK_STEAM_COMPILE_REASON_ABI_H
#define MDECK_STEAM_COMPILE_REASON_ABI_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define SR_MAGIC UINT64_C(0x4d4452434d503031)
#define SR_HISTORY 65536
#define SR_THREADS 128
#define SR_PROBES 8
#define SR_MAX_BYTES 16384
#define SR_MAX_INSTRUCTIONS 2048
#define SR_MAX_COMPLETIONS 400000
enum sr_kind { SR_FIRST, SR_CHANGED, SR_NEW_GENERATION, SR_SAME_GENERATION, SR_UNKNOWN, SR_KINDS };
enum sr_outcome { SR_GENERATED, SR_RACED, SR_FAILED, SR_DELIVERY, SR_OUTCOMES };
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
struct sr_thread {
    uint64_t epoch, instance;
    unsigned pid, tid, path, reserved;
    struct sr_metric kind[SR_KINDS];
    uint64_t outcome[SR_OUTCOMES];
};
struct sr_bridge {
    uint64_t magic, bytes, frequency, active_epoch, gate, next_instance, attached;
    uint64_t begun, attempts, dropped, classified, fingerprint_bytes;
    uint64_t history_used, history_full, shape_changed, missing_fingerprint, missing_generation;
    uint64_t out_of_order, thread_overflow;
    struct sr_metric kind[SR_KINDS];
    uint64_t outcome[SR_OUTCOMES];
    struct sr_thread threads[SR_THREADS];
    struct sr_history history[SR_HISTORY];
};
struct sr_ticket { uint64_t epoch, instance, order; unsigned pid, tid, path, reserved; };
static inline int sr_lock(struct sr_bridge *b) {
    uint64_t zero=0;
    return __atomic_compare_exchange_n(&b->gate,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static inline void sr_unlock(struct sr_bridge *b) { __atomic_store_n(&b->gate,0,__ATOMIC_RELEASE); }
static inline uint64_t sr_mix(uint64_t n) {
    n^=n>>30;n*=UINT64_C(0xbf58476d1ce4e5b9);n^=n>>27;n*=UINT64_C(0x94d049bb133111eb);return n^(n>>31);
}
static inline unsigned sr_index(struct sr_key k) {
    return (unsigned)sr_mix(k.instance^sr_mix(k.owner)^sr_mix(k.rip)^sr_mix(k.max_inst)^k.mode)&(SR_HISTORY-1);
}
static inline int sr_key_equal(struct sr_key a,struct sr_key b) {
    return a.instance==b.instance&&a.owner==b.owner&&a.rip==b.rip&&a.max_inst==b.max_inst&&a.mode==b.mode;
}
static inline enum sr_kind sr_classify(struct sr_bridge *b,struct sr_ticket t,struct sr_key key,
                                      struct sr_fingerprint f,uint64_t generation) {
    if (f.invalid||!f.instructions||!f.bytes) { b->missing_fingerprint++;return SR_UNKNOWN; }
    if (!generation||!key.owner) { b->missing_generation++;return SR_UNKNOWN; }
    unsigned start=sr_index(key);
    for (unsigned j=0;j<SR_PROBES;j++) {
        struct sr_history *h=&b->history[(start+j)&(SR_HISTORY-1)];
        if (h->epoch!=t.epoch) {
            *h=(struct sr_history){.epoch=t.epoch,.key=key,.fingerprint=f,.generation=generation,.order=t.order};
            b->history_used++;return SR_FIRST;
        }
        if (!sr_key_equal(h->key,key)) continue;
        /* Two simultaneous compiles can finish out of start order. Do not
         * overwrite the newer observation with the late older observation. */
        if (t.order<=h->order) { b->out_of_order++;return SR_UNKNOWN; }
        enum sr_kind kind;
        if (f.shape!=h->fingerprint.shape||f.bytes!=h->fingerprint.bytes||f.instructions!=h->fingerprint.instructions) {
            b->shape_changed++;kind=SR_UNKNOWN;
        } else if (f.content_a!=h->fingerprint.content_a||f.content_b!=h->fingerprint.content_b) kind=SR_CHANGED;
        else kind=generation!=h->generation?SR_NEW_GENERATION:SR_SAME_GENERATION;
        h->fingerprint=f;h->generation=generation;h->order=t.order;return kind;
    }
    /* No eviction: overflow must never turn an old address into a first. */
    b->history_full++;return SR_UNKNOWN;
}
static inline struct sr_ticket sr_begin(struct sr_bridge *b,uint64_t instance,unsigned pid,unsigned tid,unsigned path) {
    struct sr_ticket t={0,0,0,0,0,0,0};
    if (!b||!instance||!pid||!tid) return t;
    t.epoch=__atomic_load_n(&b->active_epoch,__ATOMIC_ACQUIRE);
    if (!t.epoch) return t;
    t.instance=instance;t.pid=pid;t.tid=tid;t.path=path;
    t.order=__atomic_fetch_add(&b->begun,1,__ATOMIC_RELAXED)+1;
    return t;
}
static inline void sr_add(struct sr_metric *m,uint64_t ticks) {
    m->count++;m->ticks+=ticks;if(ticks>m->max_ticks)m->max_ticks=ticks;
}
static inline int sr_finish(struct sr_bridge *b,struct sr_ticket t,struct sr_key key,
                            struct sr_fingerprint f,uint64_t generation,unsigned outcome,uint64_t ticks) {
    if (!b||!t.epoch||outcome>=SR_OUTCOMES||__atomic_load_n(&b->active_epoch,__ATOMIC_ACQUIRE)!=t.epoch) return 0;
    if (!sr_lock(b)) { __atomic_fetch_add(&b->dropped,1,__ATOMIC_RELAXED);return 0; }
    if (__atomic_load_n(&b->active_epoch,__ATOMIC_ACQUIRE)!=t.epoch||b->attempts>=SR_MAX_COMPLETIONS) {sr_unlock(b);return 0;}
    b->attempts++;b->outcome[outcome]++;
    enum sr_kind kind=SR_UNKNOWN;
    if(outcome==SR_GENERATED) {
        key.instance=t.instance;kind=sr_classify(b,t,key,f,generation);
        sr_add(&b->kind[kind],ticks);b->classified++;b->fingerprint_bytes+=f.bytes;
    }
    unsigned index=(unsigned)sr_mix(t.instance^t.tid)&(SR_THREADS-1);
    struct sr_thread *thread=0;
    for(unsigned j=0;j<SR_PROBES;j++) {
        struct sr_thread *s=&b->threads[(index+j)&(SR_THREADS-1)];
        if(s->epoch!=t.epoch){memset(s,0,sizeof(*s));s->epoch=t.epoch;s->instance=t.instance;s->pid=t.pid;s->tid=t.tid;s->path=t.path;thread=s;break;}
        if(s->instance==t.instance&&s->tid==t.tid){thread=s;break;}
    }
    if(thread) {thread->outcome[outcome]++;if(outcome==SR_GENERATED)sr_add(&thread->kind[kind],ticks);}
    else b->thread_overflow++;
    sr_unlock(b);return 1;
}
#endif
