/* mdeck CEF/native hotspot sampler. No guest execution/memory policy changes.
 * Its only suspended interval is sh_capture_thread; all lookup, aggregation,
 * locks and output run after resume. No shared legacy profiler state. */
#include "steam_hotspot.h"
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <mach/mach_vm.h>
#include <mach/arm/thread_status.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <dlfcn.h>
#include <errno.h>
#include <time.h>
#include <unistd.h>
#include <sys/qos.h>

extern pthread_key_t ios_teb_tls_key __attribute__((weak));
extern void *ios_jit_rx_base_global __attribute__((weak));
extern size_t ios_jit_pool_size_global __attribute__((weak));
extern int ios_jit_low_contains(uintptr_t) __attribute__((weak));
extern int ios_jit_pool_image_pc(uintptr_t, uintptr_t *) __attribute__((weak));

#define SH_THREADS 32
#define SH_BUCKETS 24
#define SH_PREVIOUS 256
struct sh_thread {
    uint64_t id;
    unsigned pid, tid, group, samples, states[SH_KINDS], blocked, bucket_overflow;
    double selected_cpu_ms;
    char name[64];
    struct sh_bucket buckets[SH_BUCKETS];
};
struct sh_run {
    uint64_t epoch, started, report_at, held_ns, hold_max;
    unsigned attempts, success, suspend_failed, state_failed, resume_failed, query_failed;
    unsigned selected_overflow, previous_overflow, no_candidate, rounds, threads_used;
    struct sh_thread threads[SH_THREADS];
    struct { uint64_t id, cpu_us; unsigned round; } previous[SH_PREVIOUS];
};
struct sh_candidate { uint64_t id, teb; unsigned pid, tid, group, index, run_state; double cpu_ms; char name[64]; };
struct sh_module { uint64_t base, size; char name[48]; };
static pthread_mutex_t sh_control = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t sh_wake = PTHREAD_COND_INITIALIZER;
static _Atomic uint64_t sh_epoch, sh_main_id;
static atomic_int sh_enabled;
static atomic_int sh_active;
static int sh_worker_started;
static mach_timebase_info_data_t sh_timebase;

static uint64_t sh_now(void) {
    return (uint64_t)((__uint128_t)mach_absolute_time() * sh_timebase.numer / sh_timebase.denom);
}
static int sh_read(uint64_t address, void *out, size_t size) {
    mach_vm_size_t got = 0;
    return address > 0x10000 && address <= UINT64_MAX - size &&
        mach_vm_read_overwrite(mach_task_self(), address, size, (mach_vm_address_t)out, &got) == KERN_SUCCESS && got == size;
}
/* Self-calibrate a private pthread key; never borrow the legacy sampler's
 * mutable maps or scan the suspended thread's pthread structure. */
static long sh_tsd_offset = -1;
static void sh_calibrate(void) {
    pthread_key_t key;
    if (!&ios_teb_tls_key || pthread_key_create(&key, NULL)) return;
    uintptr_t marker = (uintptr_t)&key;
    if (!pthread_setspecific(key, (void *)marker)) {
        for (long offset = 0; offset < 8192; offset += 8) {
            uintptr_t value = 0;
            if (sh_read((uintptr_t)pthread_self() + offset + (uint64_t)key * 8, &value, sizeof(value)) && value == marker) {
                sh_tsd_offset = offset; break;
            }
        }
    }
    pthread_setspecific(key, NULL); pthread_key_delete(key);
}
static uint64_t sh_teb(pthread_t thread) {
    uint64_t teb = 0;
    if (sh_tsd_offset < 0 || !thread || !&ios_teb_tls_key) return 0;
    sh_read((uintptr_t)thread + sh_tsd_offset + (uint64_t)ios_teb_tls_key * 8, &teb, sizeof(teb));
    return teb && !(teb & 0xfff) ? teb : 0;
}
static void sh_clean(char *s) {
    for (; *s; s++) if ((unsigned char)*s < 33 || (unsigned char)*s > 126 || *s == '"') *s = '_';
}
static int sh_cef_name(const char *name) {
    return !strcmp(name, "Chrome_InProcRendererThread") || !strcmp(name, "VizCompositorThread") ||
           !strcmp(name, "CrBrowserMain") || !strcmp(name, "Compositor");
}
static uint64_t sh_cpu_us(thread_basic_info_data_t info) {
    return ((uint64_t)info.user_time.seconds + info.system_time.seconds) * 1000000ull +
           info.user_time.microseconds + info.system_time.microseconds;
}
static double sh_cpu_delta(struct sh_run *run, uint64_t id, uint64_t cpu_us) {
    int empty = -1, stale = -1;
    for (unsigned i = 0; i < SH_PREVIOUS; i++) {
        if (run->previous[i].id == id) {
            double delta = run->previous[i].round + 1 == run->rounds && cpu_us >= run->previous[i].cpu_us
                ? (cpu_us - run->previous[i].cpu_us) / 1000.0 : 0;
            run->previous[i].cpu_us = cpu_us; run->previous[i].round = run->rounds;
            return delta;
        }
        if (!run->previous[i].id) empty = (int)i;
        else if (run->previous[i].round + 2 < run->rounds) stale = (int)i;
    }
    int i = empty >= 0 ? empty : stale;
    if (i >= 0) { run->previous[i].id = id; run->previous[i].cpu_us = cpu_us; run->previous[i].round = run->rounds; }
    else run->previous_overflow++;
    return 0;
}
/* All three callbacks below are used only during capture. No log/lookup/lock. */
static uint64_t sh_capture_now(void *context) { (void)context; return sh_now(); }
static int sh_suspend(void *context, uintptr_t thread) { (void)context; return thread_suspend((thread_act_t)thread); }
static int sh_resume(void *context, uintptr_t thread) { (void)context; return thread_resume((thread_act_t)thread); }
static int sh_state(void *context, uintptr_t thread, struct sh_registers *out) {
    (void)context;
    arm_thread_state64_t state; mach_msg_type_number_t count = ARM_THREAD_STATE64_COUNT;
    kern_return_t result = thread_get_state((thread_act_t)thread, ARM_THREAD_STATE64, (thread_state_t)&state, &count);
    if (result != KERN_SUCCESS) return result;
    out->pc = arm_thread_state64_get_pc(state); out->lr = arm_thread_state64_get_lr(state);
    /* Only a candidate hint. It is never used to decide the host-PC class,
     * and is not claimed as the current x86 instruction. */
    if (state.__x[28] <= UINT64_MAX - 0x18) sh_read(state.__x[28] + 0x18, &out->frame_rip, 8);
    return 0;
}
static const struct sh_capture_ops sh_ops = {sh_capture_now, sh_suspend, sh_state, sh_resume, NULL};

static unsigned sh_modules(uint64_t teb, struct sh_module modules[128]) {
    uint64_t peb = 0, ldr = 0, current = 0;
    if (!sh_read(teb + 0x60, &peb, 8) || !peb || !sh_read(peb + 0x18, &ldr, 8) || !ldr ||
        !sh_read(ldr + 0x10, &current, 8)) return 0;
    unsigned used = 0;
    while (current && current != ldr + 0x10 && used < 128) {
        unsigned char entry[0x70];
        if (!sh_read(current, entry, sizeof(entry))) break;
        uint64_t next, base, buffer; uint32_t size; uint16_t length;
        memcpy(&next, entry, 8); memcpy(&base, entry + 0x30, 8); memcpy(&size, entry + 0x40, 4);
        memcpy(&length, entry + 0x58, 2); memcpy(&buffer, entry + 0x60, 8);
        if (!base || !size || base > UINT64_MAX - size) break;
        struct sh_module *m = &modules[used++]; *m = (struct sh_module){.base = base, .size = size};
        uint16_t wide[47] = {0}; unsigned n = length / 2; if (n > 47) n = 47;
        if (n && sh_read(buffer, wide, n * 2)) for (unsigned i = 0; i < n; i++) m->name[i] = wide[i] < 128 ? (char)wide[i] : '?';
        sh_clean(m->name);
        if (!m->name[0]) strcpy(m->name, "unknown-pe");
        if (next == current) break;
        current = next;
    }
    return used;
}
static int sh_module_desc(uint64_t pc, struct sh_module *modules, unsigned count, char *out, size_t capacity) {
    for (unsigned i = 0; i < count; i++) if (pc >= modules[i].base && pc - modules[i].base < modules[i].size) {
        snprintf(out, capacity, "%s+0x%llx", modules[i].name, (unsigned long long)((pc - modules[i].base) & ~0xffull)); return 1;
    }
    return 0;
}
static enum sh_kind sh_describe(struct sh_candidate candidate, struct sh_registers regs, char out[176]) {
    uint64_t ab = &ios_jit_rx_base_global ? (uintptr_t)ios_jit_rx_base_global : 0;
    uint64_t size = &ios_jit_pool_size_global ? ios_jit_pool_size_global : 0;
    int in_c = ios_jit_low_contains && ios_jit_low_contains((uintptr_t)regs.pc);
    uintptr_t pe = 0;
    int copied = !in_c && ab && regs.pc >= ab && regs.pc - ab < size &&
        ios_jit_pool_image_pc && ios_jit_pool_image_pc((uintptr_t)regs.pc, &pe);
    struct sh_module modules[128];
    unsigned count = candidate.teb ? sh_modules(candidate.teb, modules) : 0;
    char pe_desc[100] = "", hint[100] = "";
    int module = sh_module_desc(copied ? pe : regs.pc, modules, count, pe_desc, sizeof(pe_desc));
    Dl_info info = {0};
    int host = !in_c && !copied && !module && !(ab && regs.pc >= ab && regs.pc-ab < size) &&
        dladdr((void *)(uintptr_t)regs.pc, &info) && info.dli_fname && info.dli_fbase;
    enum sh_kind kind = sh_classify(regs.pc, ab, size, in_c, copied, module, host);
    if (kind == SH_JIT_C || kind == SH_JIT_AB) {
        if (regs.frame_rip) sh_module_desc(regs.frame_rip, modules, count, hint, sizeof(hint));
        char *offset = strchr(hint, '+'); if (offset) *offset = 0;
        snprintf(out, 176, "%s;page=0x%llx;guest_hint=%s", in_c ? "jit-C" : "jit-AB",
            (unsigned long long)(regs.pc & ~0xfffull), hint[0] ? hint : "unresolved");
        return kind;
    }
    if (copied || module) {
        snprintf(out, 176, "%s", pe_desc[0] ? pe_desc : "pe-copy-unresolved"); return SH_PE;
    }
    if (kind == SH_HOST) {
        const char *base = strrchr(info.dli_fname, '/'); base = base ? base + 1 : info.dli_fname;
        snprintf(out, 176, "%s+0x%llx;%s+0x%llx", base,
            (unsigned long long)((regs.pc - (uintptr_t)info.dli_fbase) & ~0xffull), info.dli_sname ? info.dli_sname : "symbol-unavailable",
            (unsigned long long)(info.dli_saddr ? (regs.pc - (uintptr_t)info.dli_saddr) & ~0xffull : 0));
        sh_clean(out); return SH_HOST;
    }
    snprintf(out, 176, "unknown-pc=0x%llx;lr=0x%llx", (unsigned long long)regs.pc, (unsigned long long)regs.lr);
    return SH_UNKNOWN;
}
static void sh_add(struct sh_run *run, struct sh_candidate candidate, struct sh_capture capture) {
    unsigned i;
    for (i = 0; i < run->threads_used; i++) if (run->threads[i].id == candidate.id) break;
    if (i == run->threads_used) {
        if (i == SH_THREADS) { run->selected_overflow++; return; }
        run->threads_used++;
        run->threads[i] = (struct sh_thread){.id = candidate.id, .pid = candidate.pid, .tid = candidate.tid, .group = candidate.group};
        snprintf(run->threads[i].name, sizeof(run->threads[i].name), "%s", candidate.name[0] ? candidate.name : "unnamed");
        sh_clean(run->threads[i].name);
    }
    struct sh_thread *thread = &run->threads[i]; char desc[176];
    enum sh_kind kind = sh_describe(candidate, capture.regs, desc);
    thread->samples++; thread->states[kind]++; thread->selected_cpu_ms += candidate.cpu_ms;
    thread->blocked += candidate.run_state != TH_STATE_RUNNING;
    sh_bucket_note(thread->buckets, SH_BUCKETS, desc, capture.regs.pc, &thread->bucket_overflow);
}
static void sh_report(struct sh_run *run, const char *reason) {
    if (!atomic_load(&sh_enabled) || atomic_load(&sh_epoch) != run->epoch) return;
    uint64_t now = sh_now();
    dprintf(STDERR_FILENO, "[steam-hotspot] session=%llu t+%.3f reason=%s rounds=%u attempts=%u captured=%u suspend_failed=%u state_failed=%u resume_failed=%u "
        "held_ms=%.3f hold_max_ms=%.3f query_failed=%u previous_overflow=%u selected_overflow=%u no_candidate=%u teb_lookup=%s sample_distribution=not-CPU-percent\n",
        (unsigned long long)run->epoch, (now-run->started)/1e9, reason, run->rounds, run->attempts, run->success,
        run->suspend_failed, run->state_failed, run->resume_failed, run->held_ns/1e6, run->hold_max/1e6,
        run->query_failed, run->previous_overflow, run->selected_overflow, run->no_candidate, sh_tsd_offset >= 0 ? "available" : "unavailable");
    int printed[SH_THREADS] = {0};
    for (unsigned shown = 0; shown < 8; shown++) {
        int best = -1;
        for (unsigned i = 0; i < run->threads_used; i++) if (!printed[i] &&
            (best < 0 || run->threads[i].samples > run->threads[best].samples)) best = (int)i;
        if (best < 0) break;
        printed[best] = 1; struct sh_thread *t = &run->threads[best];
        dprintf(STDERR_FILENO, "[steam-hotspot-thread] session=%llu mach_tid=%llu pid=%04x tid=%04x group=%s name=%s samples=%u "
            "jit_AB=%u jit_C=%u pe=%u host=%u unknown=%u blocked_at_selection=%u selected_cpu_ms=%.3f bucket_overflow=%u\n",
            (unsigned long long)run->epoch, (unsigned long long)t->id, t->pid, t->tid, t->group == 1 ? "cef-name" : "unnamed-native", t->name,
            t->samples, t->states[0], t->states[1], t->states[2], t->states[3], t->states[4], t->blocked, t->selected_cpu_ms, t->bucket_overflow);
        /* Bounded heavy hitters, with their approximation error exposed. */
        unsigned bucket_printed[SH_BUCKETS] = {0};
        for (unsigned j = 0; j < 2; j++) {
            int b = -1;
            for (unsigned i = 0; i < SH_BUCKETS; i++) if (!bucket_printed[i] && t->buckets[i].hits &&
                (b < 0 || t->buckets[i].hits > t->buckets[b].hits)) b = (int)i;
            if (b < 0) break;
            bucket_printed[b] = 1;
            dprintf(STDERR_FILENO, "[steam-hotspot-pc] session=%llu mach_tid=%llu pc=0x%llx estimated_samples=%u error_bound=%u samples_min=%u location=%s\n",
                (unsigned long long)run->epoch, (unsigned long long)t->id, (unsigned long long)t->buckets[b].pc,
                t->buckets[b].hits, t->buckets[b].error, t->buckets[b].hits-t->buckets[b].error, t->buckets[b].desc);
        }
    }
    run->report_at = now;
}
static int sh_current(uint64_t epoch) { return atomic_load(&sh_enabled) && atomic_load(&sh_active) && atomic_load(&sh_epoch) == epoch; }
static const char *sh_tick(struct sh_run *run) {
    thread_act_array_t threads = NULL; mach_msg_type_number_t count = 0;
    if (task_threads(mach_task_self(), &threads, &count) != KERN_SUCCESS) { run->query_failed++; return NULL; }
    struct sh_candidate best[2] = {0};
    uint64_t self = 0; pthread_threadid_np(NULL, &self); run->rounds++;
    uint64_t main = atomic_load(&sh_main_id);
    for (unsigned i = 0; i < count; i++) {
        if (i >= 1024) { run->previous_overflow++; continue; }
        thread_identifier_info_data_t id; mach_msg_type_number_t ic = THREAD_IDENTIFIER_INFO_COUNT;
        thread_basic_info_data_t bi; mach_msg_type_number_t bc = THREAD_BASIC_INFO_COUNT;
        if (thread_info(threads[i], THREAD_IDENTIFIER_INFO, (thread_info_t)&id, &ic) != KERN_SUCCESS ||
            thread_info(threads[i], THREAD_BASIC_INFO, (thread_info_t)&bi, &bc) != KERN_SUCCESS) { run->query_failed++; continue; }
        double cpu = sh_cpu_delta(run, id.thread_id, sh_cpu_us(bi));
        if (!sh_may_sample(id.thread_id, self, main, bi.suspend_count, cpu)) continue;
        pthread_t pt = pthread_from_mach_thread_np(threads[i]); char name[64] = "";
        if (!pt || pthread_getname_np(pt, name, sizeof(name))) { run->query_failed++; continue; }
        uint64_t teb = sh_teb(pt); unsigned group = sh_cef_name(name) ? 1 : (!teb && !name[0] ? 2 : 0);
        if (!group || cpu <= best[group-1].cpu_ms) continue;
        struct sh_candidate c = {.id = id.thread_id, .teb = teb, .group = group, .index = i, .cpu_ms = cpu, .run_state = bi.run_state};
        if (teb) { sh_read(teb+0x40, &c.pid, 4); sh_read(teb+0x48, &c.tid, 4); }
        snprintf(c.name, sizeof(c.name), "%s", name); best[group-1] = c;
    }
    const char *stop = NULL;
    if (!best[0].id && !best[1].id) run->no_candidate++;
    for (unsigned i = 0; i < 2 && !stop && sh_current(run->epoch); i++) {
        if (!best[i].id || sh_phase(run->started, sh_now(), run->attempts, run->held_ns) != 1) continue;
        run->attempts++;
        struct sh_capture result = sh_capture_thread(&sh_ops, threads[best[i].index]);
        if (!result.suspended) { run->suspend_failed++; continue; }
        run->held_ns += result.held_ns; if (result.held_ns > run->hold_max) run->hold_max = result.held_ns;
        if (!result.resumed) { run->resume_failed++; stop = "resume-failed"; }
        else if (!result.state_ok) run->state_failed++;
        else if (sh_current(run->epoch)) { run->success++; sh_add(run, best[i], result); }
        if (!stop && result.held_ns > SH_ONE_HOLD_NS) stop = "single-hold-budget";
        if (!stop && run->held_ns >= SH_TOTAL_HOLD_NS) stop = "total-hold-budget";
    }
    for (unsigned i = 0; i < count; i++) mach_port_deallocate(mach_task_self(), threads[i]);
    vm_deallocate(mach_task_self(), (vm_address_t)threads, count * sizeof(*threads));
    return stop;
}
static void sh_wait_tick(void) {
    struct timespec until; clock_gettime(CLOCK_REALTIME, &until);
    until.tv_nsec += SH_TICK_NS; if (until.tv_nsec >= 1000000000) { until.tv_sec++; until.tv_nsec -= 1000000000; }
    pthread_cond_timedwait(&sh_wake, &sh_control, &until);
}
static void *sh_worker(void *unused) {
    (void)unused; pthread_setname_np("mdeck.cef-hotspot"); pthread_set_qos_class_self_np(QOS_CLASS_UTILITY, 0);
    sh_calibrate();
    pthread_mutex_lock(&sh_control);
    for (;;) {
        while (!atomic_load(&sh_enabled)) pthread_cond_wait(&sh_wake, &sh_control);
        struct sh_run run = {.epoch = atomic_load(&sh_epoch), .started = sh_now()}; run.report_at = run.started;
        pthread_mutex_unlock(&sh_control);
        const char *reason = "duration-complete";
        if (!atomic_load(&sh_main_id)) reason = "main-thread-unavailable";
        else while (sh_current(run.epoch)) {
            int phase = sh_phase(run.started, sh_now(), run.attempts, run.held_ns);
            if (phase < 0) { reason = run.attempts >= SH_MAX_SAMPLES ? "sample-budget" : "duration-complete"; break; }
            if (phase == 1) { const char *stop = sh_tick(&run); if (stop) { reason = stop; break; } }
            if (sh_now() - run.report_at >= 5000000000ull) sh_report(&run, phase ? "sampling" : "waiting");
            pthread_mutex_lock(&sh_control); if (sh_current(run.epoch)) sh_wait_tick(); pthread_mutex_unlock(&sh_control);
        }
        sh_report(&run, reason);
        pthread_mutex_lock(&sh_control);
        if (atomic_load(&sh_epoch) == run.epoch) atomic_store(&sh_enabled, 0);
    }
    return NULL;
}
void ios_steam_hotspot_set_main(uint64_t id) { atomic_store(&sh_main_id, id); }
void ios_steam_hotspot_set_active(int active) {
    atomic_store(&sh_active, !!active);
    if (!active) ios_steam_hotspot_configure(0);
}
void ios_steam_hotspot_configure(int enabled) {
    int saved = errno;
    pthread_mutex_lock(&sh_control);
    uint64_t epoch = atomic_fetch_add(&sh_epoch, 1) + 1;
    int was = atomic_exchange(&sh_enabled, !!enabled), activated = !!enabled;
    if (enabled && !atomic_load(&sh_active)) {
        activated = 0; atomic_store(&sh_enabled, 0);
        dprintf(STDERR_FILENO, "[steam-hotspot] session=%llu reason=app-inactive\n", (unsigned long long)epoch);
    }
    if (activated && !sh_worker_started) {
        mach_timebase_info(&sh_timebase);
        pthread_t thread; int error = pthread_create(&thread, NULL, sh_worker, NULL);
        if (!error) { pthread_detach(thread); sh_worker_started = 1; }
        else { activated = 0; atomic_store(&sh_enabled, 0); dprintf(STDERR_FILENO, "[steam-hotspot] session=%llu reason=worker-create-failed error=%d\n", (unsigned long long)epoch, error); }
    }
    pthread_cond_broadcast(&sh_wake);
    pthread_mutex_unlock(&sh_control);
    if (activated) dprintf(STDERR_FILENO, "[steam-hotspot] enabled session=%llu delay=15s duration=30s tick=200ms max_samples=300 "
        "max_targets_per_tick=2 single_hold_budget_ms=5 total_hold_budget_ms=50 guest_hint=not-exact-RIP\n", (unsigned long long)epoch);
    else if (was && !enabled) dprintf(STDERR_FILENO, "[steam-hotspot] disabled session=%llu\n", (unsigned long long)epoch);
    errno = saved;
}
