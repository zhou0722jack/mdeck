/* mdeck-only FEX diagnostic bridge. Shared native/PE layout; no callbacks.
 * All gates are try-locks: delivery/reentrant compiles must never wait on a
 * profiler lock held by the interrupted thread. No allocation or logging. */
#ifndef MDECK_STEAM_PROBE_ABI_H
#define MDECK_STEAM_PROBE_ABI_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define SF_MAGIC UINT64_C(0x4d44465350523031)
#define SF_SLOTS 64
#define SF_PROBES 4
enum sf_stage { SF_DISPATCH, SF_LOOKUP, SF_COMPILE, SF_CLEAR, SF_MIGRATE, SF_SWEEP, SF_STAGES };
struct sf_metric { uint64_t calls, samples, ticks, max_ticks; };
struct sf_slot {
    uint64_t gate, epoch, teb, mach_tid;
    uint32_t pid, tid;
    struct sf_metric metric[SF_STAGES];
};
struct sf_bridge {
    uint64_t magic, bytes, active_epoch, frequency, attached, dropped;
    struct sf_slot slots[SF_SLOTS];
};
struct sf_ticket { struct sf_slot *slot; uint64_t epoch; unsigned stage; };
static inline int sf_lock(struct sf_slot *s) {
    uint64_t zero = 0;
    return __atomic_compare_exchange_n(&s->gate, &zero, 1, 0, __ATOMIC_ACQUIRE, __ATOMIC_RELAXED);
}
static inline void sf_unlock(struct sf_slot *s) { __atomic_store_n(&s->gate, 0, __ATOMIC_RELEASE); }
static inline unsigned sf_hash(uint64_t teb) { return (unsigned)((teb >> 12) ^ (teb >> 20)) & (SF_SLOTS - 1); }
static inline unsigned sf_stride(unsigned stage) { return stage == SF_DISPATCH || stage == SF_LOOKUP ? 64 : 1; }
/* Host-only enrollment; at most four slots searched, no eviction within a
 * session. Old scopes carry an epoch and cannot update a reused slot. */
static inline int sf_enroll(struct sf_bridge *b, uint64_t epoch, uint64_t teb,
                            uint64_t mach_tid, unsigned pid, unsigned tid) {
    if (!teb || !mach_tid || !pid || !tid || !epoch ||
        __atomic_load_n(&b->active_epoch, __ATOMIC_ACQUIRE) != epoch) return 0;
    for (unsigned j = 0; j < SF_PROBES; j++) {
        struct sf_slot *s = &b->slots[(sf_hash(teb) + j) & (SF_SLOTS - 1)];
        if (!sf_lock(s)) return 0;
        if (s->epoch == epoch && s->teb == teb) {
            int same = s->mach_tid == mach_tid && s->tid == tid;
            sf_unlock(s); return same;
        }
        if (s->epoch != epoch) {
            memset(s->metric, 0, sizeof(s->metric));
            s->mach_tid = mach_tid; s->pid = pid; s->tid = tid;
            __atomic_store_n(&s->teb, teb, __ATOMIC_RELAXED);
            __atomic_store_n(&s->epoch, epoch, __ATOMIC_RELEASE);
            sf_unlock(s); return 1;
        }
        sf_unlock(s);
    }
    return 0;
}
static inline struct sf_ticket sf_enter(struct sf_bridge *b, uint64_t teb, unsigned tid, unsigned stage) {
    struct sf_ticket t = {0, 0, stage};
    if (!b || !teb || stage >= SF_STAGES) return t;
    uint64_t epoch = __atomic_load_n(&b->active_epoch, __ATOMIC_ACQUIRE);
    if (!epoch) return t;
    for (unsigned j = 0; j < SF_PROBES; j++) {
        struct sf_slot *s = &b->slots[(sf_hash(teb) + j) & (SF_SLOTS - 1)];
        if (__atomic_load_n(&s->epoch, __ATOMIC_ACQUIRE) != epoch ||
            __atomic_load_n(&s->teb, __ATOMIC_RELAXED) != teb) continue;
        if (!sf_lock(s)) { __atomic_fetch_add(&b->dropped, 1, __ATOMIC_RELAXED); return t; }
        if (s->epoch == epoch && s->teb == teb && s->tid == tid &&
            __atomic_load_n(&b->active_epoch, __ATOMIC_ACQUIRE) == epoch) {
            uint64_t calls = ++s->metric[stage].calls;
            if ((calls - 1) % sf_stride(stage) == 0) { t.slot = s; t.epoch = epoch; }
        }
        sf_unlock(s); return t;
    }
    return t;
}
static inline void sf_leave(struct sf_bridge *b, struct sf_ticket t, uint64_t start, uint64_t end) {
    if (!t.slot || end < start || __atomic_load_n(&b->active_epoch, __ATOMIC_ACQUIRE) != t.epoch) return;
    if (!sf_lock(t.slot)) { __atomic_fetch_add(&b->dropped, 1, __ATOMIC_RELAXED); return; }
    if (t.slot->epoch == t.epoch && __atomic_load_n(&b->active_epoch, __ATOMIC_ACQUIRE) == t.epoch) {
        struct sf_metric *m = &t.slot->metric[t.stage];
        uint64_t elapsed = end - start;
        m->samples++; m->ticks += elapsed;
        if (elapsed > m->max_ticks) m->max_ticks = elapsed;
    }
    sf_unlock(t.slot);
}
#endif
