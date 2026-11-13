/* mdeck Steam allocation diagnostics. No allocation policy changes.
 * Included once by virtual_ios.c; tests execute this same implementation.
 * Durations are monotonic wall time, not CPU time. */
#ifndef MDECK_STEAM_ALLOC_STATS_H
#define MDECK_STEAM_ALLOC_STATS_H
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <unistd.h>

#define IOS_SA_SLOTS 128
#define IOS_SA_TOP 8
#define IOS_SA_CONFLICT 0xc0000018u
struct ios_sa_time { uint64_t ns, max, n; };
struct ios_sa_counts {
    uint64_t requests, success, failed, final_conflict, hinted, remote, retry_requests, retries;
    uint64_t attempts, attempt_failed, conflicts, hinted_conflicts, recovered;
    uint64_t low_try, low_success, low_miss, fallback_success, fallback_failed;
    uint64_t bytes, min_size, max_size;
    struct ios_sa_time total, attempt, conflict, hinted_conflict, retry, low, fallback;
};
struct ios_sa_row {
    unsigned pid, tid, api, bucket, types;
    int used;
    struct ios_sa_counts c;
};
struct ios_sa_request {
    uint64_t epoch, started;
    unsigned attempt_depth;
    int root;
    struct ios_sa_row row;
};
struct ios_sa_fallback { struct ios_sa_request *request; uint64_t started; };
static pthread_mutex_t ios_sa_lock = PTHREAD_MUTEX_INITIALIZER;
static int ios_sa_on;
static uint64_t ios_sa_epoch, ios_sa_started, ios_sa_since, ios_sa_overflow;
static struct ios_sa_counts ios_sa_total, ios_sa_unlisted;
static struct ios_sa_row ios_sa_rows[IOS_SA_SLOTS];
static _Thread_local struct ios_sa_request *ios_sa_current;

static inline uint64_t ios_sa_now(void) {
    int saved = errno;
    struct timespec ts;
    int rc = clock_gettime(CLOCK_MONOTONIC, &ts);
    errno = saved;
    return rc ? 0 : (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}
static inline uint64_t ios_sa_elapsed(uint64_t now, uint64_t before) {
    return before && now >= before ? now - before : 0;
}
static inline void ios_sa_time_add(struct ios_sa_time *t, uint64_t ns) {
    t->n++; t->ns += ns; if (ns > t->max) t->max = ns;
}
static inline void ios_sa_time_merge(struct ios_sa_time *a, const struct ios_sa_time *b) {
    a->n += b->n; a->ns += b->ns; if (b->max > a->max) a->max = b->max;
}
static inline unsigned ios_sa_size_bucket(uint64_t size) {
    const uint64_t bounds[] = {0x10000, 0x100000, 0x400000, 0x1000000, 0x8000000, 0x40000000};
    for (unsigned i = 0; i < sizeof(bounds) / sizeof(bounds[0]); i++) if (size < bounds[i]) return i;
    return 6;
}
static inline void ios_sa_merge(struct ios_sa_counts *a, const struct ios_sa_counts *b) {
    if (b->requests && (!a->requests || b->min_size < a->min_size)) a->min_size = b->min_size;
    if (b->max_size > a->max_size) a->max_size = b->max_size;
#define IOS_SA_SUM(f) a->f += b->f
    IOS_SA_SUM(requests); IOS_SA_SUM(success); IOS_SA_SUM(failed); IOS_SA_SUM(final_conflict);
    IOS_SA_SUM(hinted); IOS_SA_SUM(remote); IOS_SA_SUM(retry_requests); IOS_SA_SUM(retries);
    IOS_SA_SUM(attempts); IOS_SA_SUM(attempt_failed); IOS_SA_SUM(conflicts); IOS_SA_SUM(hinted_conflicts);
    IOS_SA_SUM(recovered); IOS_SA_SUM(low_try); IOS_SA_SUM(low_success); IOS_SA_SUM(low_miss);
    IOS_SA_SUM(fallback_success); IOS_SA_SUM(fallback_failed); IOS_SA_SUM(bytes);
#undef IOS_SA_SUM
#define IOS_SA_MERGE(f) ios_sa_time_merge(&a->f, &b->f)
    IOS_SA_MERGE(total); IOS_SA_MERGE(attempt); IOS_SA_MERGE(conflict); IOS_SA_MERGE(hinted_conflict);
    IOS_SA_MERGE(retry); IOS_SA_MERGE(low); IOS_SA_MERGE(fallback);
#undef IOS_SA_MERGE
}

/* Called after the effective game/global environment and log output are ready.
 * No getenv on allocator hot paths; epoch invalidates unfinished old requests. */
void ios_steam_alloc_stats_configure(int enabled, uint64_t epoch) {
    int saved = errno;
    pthread_mutex_lock(&ios_sa_lock);
    __atomic_store_n(&ios_sa_on, 0, __ATOMIC_RELEASE);
    __atomic_store_n(&ios_sa_epoch, epoch, __ATOMIC_RELEASE);
    ios_sa_started = ios_sa_since = ios_sa_now();
    memset(ios_sa_rows, 0, sizeof(ios_sa_rows));
    ios_sa_total = ios_sa_unlisted = (struct ios_sa_counts){0}; ios_sa_overflow = 0;
    __atomic_store_n(&ios_sa_on, !!enabled, __ATOMIC_RELEASE);
    pthread_mutex_unlock(&ios_sa_lock);
    if (enabled) dprintf(STDERR_FILENO, "[steam-alloc] enabled session=%llu interval=1s ms=mean/max/count "
        "wall-time (not CPU); request=one NtAllocateVirtualMemory/Ex call; attempt=outer allocate_virtual_memory call; "
        "separate guest API retries are separate requests; top=%d slots=%d\n",
        (unsigned long long)epoch, IOS_SA_TOP, IOS_SA_SLOTS);
    errno = saved;
}

static inline void ios_sa_begin(struct ios_sa_request *r, unsigned pid, unsigned tid, unsigned api,
                                 uint64_t size, uintptr_t hint, unsigned type, int remote) {
    r->root = 0;
    if (!__atomic_load_n(&ios_sa_on, __ATOMIC_ACQUIRE) || ios_sa_current) return;
    memset(r, 0, sizeof(*r));
    r->epoch = __atomic_load_n(&ios_sa_epoch, __ATOMIC_ACQUIRE);
    r->started = ios_sa_now(); r->root = 1;
    r->row = (struct ios_sa_row){.pid = pid, .tid = tid, .api = api,
        .bucket = ios_sa_size_bucket(size), .types = type, .used = 1};
    r->row.c = (struct ios_sa_counts){.requests = 1, .hinted = !!hint, .remote = !!remote,
        .bytes = size, .min_size = size, .max_size = size};
    ios_sa_current = r;
}

static inline void ios_sa_end(struct ios_sa_request *r, unsigned status) {
    if (!r->root) return;
    int saved = errno;
    struct ios_sa_counts *c = &r->row.c;
    ios_sa_time_add(&c->total, ios_sa_elapsed(ios_sa_now(), r->started));
    if (status) c->failed++; else c->success++;
    c->final_conflict += status == IOS_SA_CONFLICT;
    c->recovered += !status && c->conflicts > 0;
    c->retry_requests += c->attempts > 1;
    c->retries += c->attempts > 1 ? c->attempts - 1 : 0;
    if (c->low_miss) { if (status) c->fallback_failed++; else c->fallback_success++; }
    ios_sa_current = NULL;
    pthread_mutex_lock(&ios_sa_lock);
    if (__atomic_load_n(&ios_sa_on, __ATOMIC_RELAXED) && r->epoch == ios_sa_epoch) {
        ios_sa_merge(&ios_sa_total, c);
        struct ios_sa_row *slot = NULL;
        for (unsigned i = 0; i < IOS_SA_SLOTS; i++) {
            struct ios_sa_row *p = &ios_sa_rows[i];
            if (!p->used) { if (!slot) slot = p; continue; }
            if (p->pid == r->row.pid && p->tid == r->row.tid && p->api == r->row.api && p->bucket == r->row.bucket) {
                slot = p; break;
            }
        }
        if (slot) {
            if (!slot->used) { *slot = r->row; slot->c = (struct ios_sa_counts){0}; }
            slot->types |= r->row.types;
            ios_sa_merge(&slot->c, c);
        } else { ios_sa_overflow++; ios_sa_merge(&ios_sa_unlisted, c); }
    }
    pthread_mutex_unlock(&ios_sa_lock);
    errno = saved;
}

/* Only outer internal calls count as attempts: nested thin-reservation helper
 * calls would otherwise double count the same time. All real attempts still
 * execute, regardless of whether diagnostics are enabled. */
struct ios_sa_attempt { struct ios_sa_request *request; uint64_t started; int outer, hinted, retry; };
static inline struct ios_sa_attempt ios_sa_attempt_begin(uintptr_t hint) {
    struct ios_sa_attempt a = {.request = ios_sa_current};
    if (!a.request) return a;
    a.outer = a.request->attempt_depth++ == 0;
    if (a.outer) {
        a.started = ios_sa_now(); a.hinted = !!hint;
        a.retry = a.request->row.c.attempts > 0;
        a.request->row.c.attempts++;
    }
    return a;
}
static inline void ios_sa_attempt_end(struct ios_sa_attempt a, unsigned status) {
    if (!a.request) return;
    a.request->attempt_depth--;
    if (!a.outer) return;
    struct ios_sa_counts *c = &a.request->row.c;
    uint64_t elapsed = ios_sa_elapsed(ios_sa_now(), a.started);
    ios_sa_time_add(&c->attempt, elapsed);
    if (a.retry) ios_sa_time_add(&c->retry, elapsed);
    c->attempt_failed += status != 0;
    if (status == IOS_SA_CONFLICT) {
        c->conflicts++; ios_sa_time_add(&c->conflict, elapsed);
        if (a.hinted) { c->hinted_conflicts++; ios_sa_time_add(&c->hinted_conflict, elapsed); }
    }
}

static inline uint64_t ios_sa_stage_begin(void) { return ios_sa_current ? ios_sa_now() : 0; }
static inline void ios_sa_low_result(uint64_t began, int success) {
    if (!began || !ios_sa_current) return;
    struct ios_sa_counts *c = &ios_sa_current->row.c;
    c->low_try++; if (success) c->low_success++; else c->low_miss++;
    ios_sa_time_add(&c->low, ios_sa_elapsed(ios_sa_now(), began));
}
static inline void ios_sa_fallback_begin(struct ios_sa_fallback *scope) {
    if (!scope->request && ios_sa_current) { scope->request = ios_sa_current; scope->started = ios_sa_now(); }
}
static inline void ios_sa_fallback_end(struct ios_sa_fallback *scope) {
    if (scope->request && scope->started)
        ios_sa_time_add(&scope->request->row.c.fallback, ios_sa_elapsed(ios_sa_now(), scope->started));
}

static void ios_sa_print(const char *kind, uint64_t epoch, double elapsed, double dt,
                          const struct ios_sa_row *r, uint64_t overflow) {
    const struct ios_sa_counts *c = &r->c;
    const char *sizes[] = {"lt64K", "64K-lt1M", "1M-lt4M", "4M-lt16M", "16M-lt128M", "128M-lt1G", "ge1G"};
#define SA_U(f) (unsigned long long)c->f
#define SA_MS(f) (c->f.n ? c->f.ns / (1e6 * c->f.n) : 0), c->f.max / 1e6, (unsigned long long)c->f.n
    dprintf(STDERR_FILENO, "[steam-alloc] session=%llu t+%.3f dt=%.3f kind=%s pid=%04x tid=%04x api=%s size=%s "
        "min_bytes=%llu max_bytes=%llu requestedMiB=%.3f types=0x%x "
        "requests=%llu success=%llu failed=%llu final_conflict=%llu hinted=%llu remote=%llu "
        "attempts=%llu attempt_failed=%llu conflicts=%llu hinted_conflicts=%llu recovered=%llu retry_requests=%llu retries=%llu "
        "low_try=%llu low_success=%llu low_miss=%llu fallback_success=%llu fallback_failed=%llu overflow=%llu "
        "wall_ms_sum=%.3f total_ms=%.3f/%.3f/%llu attempt_ms=%.3f/%.3f/%llu conflict_ms=%.3f/%.3f/%llu "
        "hinted_conflict_ms=%.3f/%.3f/%llu retry_ms=%.3f/%.3f/%llu low_ms=%.3f/%.3f/%llu fallback_ms=%.3f/%.3f/%llu\n",
        (unsigned long long)epoch, elapsed, dt, kind, r->pid, r->tid,
        r->api == 1 ? "NtAllocateVirtualMemory" : r->api == 2 ? "NtAllocateVirtualMemoryEx" : "all",
        r->api ? sizes[r->bucket] : "all", SA_U(min_size), SA_U(max_size), c->bytes / 1048576.0, r->types,
        SA_U(requests), SA_U(success), SA_U(failed), SA_U(final_conflict), SA_U(hinted), SA_U(remote),
        SA_U(attempts), SA_U(attempt_failed), SA_U(conflicts), SA_U(hinted_conflicts), SA_U(recovered),
        SA_U(retry_requests), SA_U(retries), SA_U(low_try), SA_U(low_success), SA_U(low_miss),
        SA_U(fallback_success), SA_U(fallback_failed), (unsigned long long)overflow,
        c->total.ns / 1e6, SA_MS(total), SA_MS(attempt), SA_MS(conflict), SA_MS(hinted_conflict),
        SA_MS(retry), SA_MS(low), SA_MS(fallback));
#undef SA_U
#undef SA_MS
}

/* Same utility timer as [steam-surface]. Copy/reset under one short lock, then
 * log outside allocator locks. Counters include ALL completed API requests;
 * keyed slots only bound attribution detail. No per-allocation output. */
void ios_steam_alloc_stats_report(uint64_t epoch) {
    struct ios_sa_row snapshot[IOS_SA_SLOTS], total = {0}, unlisted = {0};
    uint64_t overflow, started, since, now = ios_sa_now();
    int saved = errno;
    pthread_mutex_lock(&ios_sa_lock);
    if (!__atomic_load_n(&ios_sa_on, __ATOMIC_RELAXED) || epoch != ios_sa_epoch) {
        pthread_mutex_unlock(&ios_sa_lock); errno = saved; return;
    }
    memcpy(snapshot, ios_sa_rows, sizeof(snapshot)); memset(ios_sa_rows, 0, sizeof(ios_sa_rows));
    total.c = ios_sa_total; unlisted.c = ios_sa_unlisted; overflow = ios_sa_overflow;
    started = ios_sa_started; since = ios_sa_since; ios_sa_since = now;
    ios_sa_total = ios_sa_unlisted = (struct ios_sa_counts){0}; ios_sa_overflow = 0;
    pthread_mutex_unlock(&ios_sa_lock);
    double dt = ios_sa_elapsed(now, since) / 1e9, elapsed = ios_sa_elapsed(now, started) / 1e9;
    if (dt <= 0) { errno = saved; return; }
    ios_sa_print("total", epoch, elapsed, dt, &total, overflow);
    for (unsigned k = 0; k < IOS_SA_TOP; k++) {
        int best = -1;
        for (unsigned i = 0; i < IOS_SA_SLOTS; i++)
            if (snapshot[i].used && (best < 0 || snapshot[i].c.total.ns > snapshot[best].c.total.ns)) best = (int)i;
        if (best < 0) break;
        ios_sa_print("thread-size", epoch, elapsed, dt, &snapshot[best], overflow);
        snapshot[best].used = 0;
    }
    /* Every unprinted request remains visible in a remainder aggregate. */
    for (unsigned i = 0; i < IOS_SA_SLOTS; i++) if (snapshot[i].used) ios_sa_merge(&unlisted.c, &snapshot[i].c);
    if (unlisted.c.requests) ios_sa_print("remainder", epoch, elapsed, dt, &unlisted, overflow);
    errno = saved;
}
#endif
