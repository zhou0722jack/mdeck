/* Steam's GDI -> owned snapshot -> CGImage -> CALayer diagnostics.
 * All state is bounded and protected by the caller's lock. Times are monotonic
 * seconds; measured stages are wall time, not CPU time or GPU/display time. */
#ifndef WINIOS_SURFACE_STATS_H
#define WINIOS_SURFACE_STATS_H

#include <stdint.h>
#include <string.h>

#define WINIOS_SURFACE_STATS_SLOTS 64
enum winios_surface_role { WINIOS_SURFACE_MAIN, WINIOS_SURFACE_STEAM_OTHER,
    WINIOS_SURFACE_OTHER, WINIOS_SURFACE_UNKNOWN, WINIOS_SURFACE_CURSOR, WINIOS_SURFACE_ROLES };

struct winios_surface_time { uint64_t n; double sum, max; };
struct winios_surface_counts {
    uint64_t received, queued, applied, skipped, failed, copied_bytes, dirty_pixels;
    uint64_t pending, pending_bytes, peak_pending, peak_bytes;
    struct winios_surface_time copy, prepare, queue, image, layer, main, total;
};
struct winios_surface_slot {
    uintptr_t hwnd;
    uint64_t serial, in_flight;
    unsigned pid;
    int live, owner_checked, steam, visible, width, height;
    struct winios_surface_counts counts;
};
struct winios_surface_stats {
    uint64_t epoch, next_serial, overflow;
    double since;
    struct winios_surface_slot slots[WINIOS_SURFACE_STATS_SLOTS];
};
struct winios_surface_ticket {
    uint64_t epoch, serial, bytes;
    int slot;
    double began, enqueued;
};

static inline void winios_surface_time_add(struct winios_surface_time *t, double seconds) {
    double ms = seconds > 0 ? seconds * 1000 : 0;
    t->n++; t->sum += ms; if (ms > t->max) t->max = ms;
}
static inline void winios_surface_time_merge(struct winios_surface_time *a, struct winios_surface_time b) {
    a->n += b.n; a->sum += b.sum; if (b.max > a->max) a->max = b.max;
}
static inline int winios_surface_is_steam(const char *image) {
    const char *base = image;
    for (const char *p = image; *p; p++) if (*p == '/' || *p == '\\') base = p + 1;
    /* Driver image paths are lower case. Match a basename, never a folder. */
    return !strcmp(base, "steam.exe") || !strcmp(base, "steamwebhelper.exe");
}
static inline struct winios_surface_slot *winios_surface_slot_for(struct winios_surface_stats *s, uintptr_t hwnd) {
    struct winios_surface_slot *empty = NULL;
    for (int i = 0; i < WINIOS_SURFACE_STATS_SLOTS; i++) {
        struct winios_surface_slot *w = &s->slots[i];
        if (w->serial && w->live && w->hwnd == hwnd) return w;
        /* A retired slot stays until its queued work and interval are drained. */
        if (!w->serial && !empty) empty = w;
    }
    if (!empty) { s->overflow++; return NULL; }
    empty->hwnd = hwnd; empty->serial = ++s->next_serial; empty->live = 1;
    return empty;
}
static inline struct winios_surface_slot *winios_surface_ticket_slot(struct winios_surface_stats *s,
                                                                     struct winios_surface_ticket t) {
    if (t.epoch != s->epoch || t.slot < 0 || t.slot >= WINIOS_SURFACE_STATS_SLOTS) return NULL;
    struct winios_surface_slot *w = &s->slots[t.slot];
    return w->serial && w->serial == t.serial ? w : NULL;
}
static inline struct winios_surface_ticket winios_surface_begin(struct winios_surface_stats *s,
                                                                uintptr_t hwnd, uint64_t bytes, double now) {
    struct winios_surface_ticket t = {.slot = -1};
    struct winios_surface_slot *w = winios_surface_slot_for(s, hwnd);
    if (!w) return t;
    t = (struct winios_surface_ticket){s->epoch, w->serial, bytes, (int)(w - s->slots), now, 0};
    w->in_flight++;
    w->counts.received++;
    return t;
}
static inline void winios_surface_copied(struct winios_surface_stats *s, struct winios_surface_ticket t,
                                         double now, uint64_t dirty_pixels) {
    struct winios_surface_slot *w = winios_surface_ticket_slot(s, t);
    if (!w) return;
    w->counts.copied_bytes += t.bytes; w->counts.dirty_pixels += dirty_pixels;
    winios_surface_time_add(&w->counts.copy, now - t.began);
}
static inline void winios_surface_enqueued(struct winios_surface_stats *s, struct winios_surface_ticket *t,
                                           double now, double copied_at) {
    struct winios_surface_slot *w = winios_surface_ticket_slot(s, *t);
    if (!w) return;
    t->enqueued = now;
    struct winios_surface_counts *c = &w->counts;
    c->queued++; c->pending++; c->pending_bytes += t->bytes;
    if (c->pending > c->peak_pending) c->peak_pending = c->pending;
    if (c->pending_bytes > c->peak_bytes) c->peak_bytes = c->pending_bytes;
    winios_surface_time_add(&c->prepare, now - copied_at);
}
/* result: 1 submitted to a layer, 0 intentionally skipped, -1 allocation/image
 * failure. queue/main timings exist even for an early return in the main block.
 * Negative image/layer times mean that stage did not execute. */
static inline void winios_surface_finished(struct winios_surface_stats *s, struct winios_surface_ticket t,
                                           int result, double main_at, double now, double image_s, double layer_s) {
    struct winios_surface_slot *w = winios_surface_ticket_slot(s, t);
    if (!w) return;
    struct winios_surface_counts *c = &w->counts;
    if (w->in_flight) w->in_flight--;
    if (result > 0) c->applied++; else if (!result) c->skipped++; else c->failed++;
    if (t.enqueued > 0) {
        if (c->pending) c->pending--;
        if (c->pending_bytes >= t.bytes) c->pending_bytes -= t.bytes;
        winios_surface_time_add(&c->queue, main_at - t.enqueued);
        winios_surface_time_add(&c->main, now - main_at);
    }
    if (image_s >= 0) winios_surface_time_add(&c->image, image_s);
    if (layer_s >= 0) winios_surface_time_add(&c->layer, layer_s);
    winios_surface_time_add(&c->total, now - t.began);
}
static inline int winios_surface_main_slot(const struct winios_surface_stats *s) {
    int best = -1; uint64_t area = 0;
    for (int i = 0; i < WINIOS_SURFACE_STATS_SLOTS; i++) {
        const struct winios_surface_slot *w = &s->slots[i];
        if (!w->live || !w->steam || !w->visible || w->width <= 0 || w->height <= 0) continue;
        uint64_t a = (uint64_t)w->width * (uint64_t)w->height;
        if (a > area) { best = i; area = a; }
    }
    return best;
}
static inline enum winios_surface_role winios_surface_role_for(const struct winios_surface_slot *w,
                                                              int index, int main_slot) {
    if (!w->hwnd) return WINIOS_SURFACE_CURSOR;
    if (index == main_slot) return WINIOS_SURFACE_MAIN;
    if (w->steam) return WINIOS_SURFACE_STEAM_OTHER;
    return w->pid ? WINIOS_SURFACE_OTHER : WINIOS_SURFACE_UNKNOWN;
}
static inline void winios_surface_counts_merge(struct winios_surface_counts *a,
                                                const struct winios_surface_counts *b) {
#define WINIOS_SURFACE_SUM(f) a->f += b->f
    WINIOS_SURFACE_SUM(received); WINIOS_SURFACE_SUM(queued); WINIOS_SURFACE_SUM(applied);
    WINIOS_SURFACE_SUM(skipped); WINIOS_SURFACE_SUM(failed); WINIOS_SURFACE_SUM(copied_bytes);
    WINIOS_SURFACE_SUM(dirty_pixels); WINIOS_SURFACE_SUM(pending); WINIOS_SURFACE_SUM(pending_bytes);
    /* Sum of each window's peak, an upper bound, not a simultaneous peak. */
    WINIOS_SURFACE_SUM(peak_pending); WINIOS_SURFACE_SUM(peak_bytes);
#undef WINIOS_SURFACE_SUM
#define WINIOS_SURFACE_TIME(f) winios_surface_time_merge(&a->f, b->f)
    WINIOS_SURFACE_TIME(copy); WINIOS_SURFACE_TIME(prepare); WINIOS_SURFACE_TIME(queue);
    WINIOS_SURFACE_TIME(image); WINIOS_SURFACE_TIME(layer); WINIOS_SURFACE_TIME(main); WINIOS_SURFACE_TIME(total);
#undef WINIOS_SURFACE_TIME
}
static inline void winios_surface_interval_reset(struct winios_surface_stats *s, double now) {
    s->since = now; s->overflow = 0;
    for (int i = 0; i < WINIOS_SURFACE_STATS_SLOTS; i++) {
        struct winios_surface_slot *w = &s->slots[i];
        uint64_t pending = w->counts.pending, bytes = w->counts.pending_bytes;
        if (!w->live && !w->in_flight) { memset(w, 0, sizeof(*w)); continue; }
        w->counts = (struct winios_surface_counts){.pending = pending, .pending_bytes = bytes,
                                                  .peak_pending = pending, .peak_bytes = bytes};
    }
}
#endif
