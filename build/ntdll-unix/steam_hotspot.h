/* Bounded, opt-in Steam PC sampling. GPL-3.0-or-later. */
#ifndef MDECK_STEAM_HOTSPOT_H
#define MDECK_STEAM_HOTSPOT_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>

#define SH_DELAY_NS 15000000000ull
#define SH_DURATION_NS 30000000000ull
#define SH_TICK_NS 200000000ull
#define SH_MAX_SAMPLES 300
#define SH_ONE_HOLD_NS 5000000ull
#define SH_TOTAL_HOLD_NS 50000000ull
enum sh_kind { SH_JIT_AB, SH_JIT_C, SH_PE, SH_HOST, SH_UNKNOWN, SH_KINDS };
struct sh_bucket { char desc[176]; uint64_t pc; unsigned hits, error; };
/* Space-saving heavy hitters: late hot locations can replace early cold
 * ones. hits is an upper estimate, hits-error a lower bound. */
static inline void sh_bucket_note(struct sh_bucket *b, unsigned count, const char *desc,
                                   uint64_t pc, unsigned *overflow) {
    if (!count) { (*overflow)++; return; }
    unsigned best = 0;
    for (unsigned i = 0; i < count; i++) {
        if (b[i].hits && !strcmp(b[i].desc, desc)) { b[i].hits++; return; }
        if (!b[i].hits) { snprintf(b[i].desc, sizeof(b[i].desc), "%s", desc); b[i].pc = pc; b[i].hits = 1; return; }
        if (b[i].hits < b[best].hits) best = i;
    }
    (*overflow)++;
    b[best].error = b[best].hits; b[best].hits++;
    b[best].pc = pc; snprintf(b[best].desc, sizeof(b[best].desc), "%s", desc);
}
struct sh_registers { uint64_t pc, lr, frame_rip; };
struct sh_capture {
    struct sh_registers regs;
    uint64_t held_ns;
    int suspended, state_ok, resumed, resume_tries;
};
/* Every operation used between suspend/resume must be allocation-free and
 * lock-free. No symbolizer, Wine lookup, logging or callback to UIKit here. */
struct sh_capture_ops {
    uint64_t (*now)(void *);
    int (*suspend)(void *, uintptr_t);
    int (*state)(void *, uintptr_t, struct sh_registers *);
    int (*resume)(void *, uintptr_t);
    void *context;
};
static inline struct sh_capture sh_capture_thread(const struct sh_capture_ops *ops, uintptr_t thread) {
    struct sh_capture r = {0};
    uint64_t start = ops->now(ops->context);
    if (ops->suspend(ops->context, thread)) return r;
    r.suspended = 1;
    r.state_ok = !ops->state(ops->context, thread, &r.regs);
    /* Failed state reads still resume. Retry transient resume errors, and
     * expose failure rather than counting such a sample as successful. */
    for (int i = 0; i < 3; i++) {
        r.resume_tries++;
        if (!ops->resume(ops->context, thread)) { r.resumed = 1; break; }
    }
    uint64_t end = ops->now(ops->context);
    r.held_ns = end >= start ? end - start : 0;
    return r;
}
static inline int sh_phase(uint64_t started, uint64_t now, unsigned attempts, uint64_t held_ns) {
    if (now < started) return -1;
    if (now - started >= SH_DELAY_NS + SH_DURATION_NS) return -1;
    if (attempts >= SH_MAX_SAMPLES || held_ns >= SH_TOTAL_HOLD_NS) return -1;
    return now - started < SH_DELAY_NS ? 0 : 1;
}
static inline int sh_may_sample(uint64_t id, uint64_t self, uint64_t main,
                                unsigned suspend_count, double cpu_ms) {
    return main && id && id != self && id != main && !suspend_count && cpu_ms >= 2.0;
}
static inline enum sh_kind sh_classify(uint64_t pc, uint64_t ab, uint64_t ab_size,
                                      int in_c, int pe_copy, int pe_module, int host_module) {
    if (in_c) return SH_JIT_C;
    if (ab && pc >= ab && pc - ab < ab_size) return pe_copy ? SH_PE : SH_JIT_AB;
    if (pe_module) return SH_PE;
    return host_module ? SH_HOST : SH_UNKNOWN;
}
void ios_steam_hotspot_set_main(uint64_t thread_id);
void ios_steam_hotspot_set_active(int active);
void ios_steam_hotspot_configure(int enabled);
#endif
