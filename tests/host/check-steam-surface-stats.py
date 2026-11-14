#!/usr/bin/env python3
"""Execute the production surface counters and timer/session adapter on macOS.

Run in GitHub Actions. No IPA, simulator or product linking is performed. The
full Winios translation unit also receives an iPhoneOS syntax-only check.
"""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
native = root / 'app/Madeira/Winios'
source = (native / 'Winios.m').read_text()
bridge = (root / 'app/Madeira/WineProcessBridge.m').read_text()
workflow = (root / '.github/workflows/build.yml').read_text()

c_test = r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "WiniosSurfaceStats.h"
static void near(double a, double b) { assert(fabs(a-b) < .000001); }
int main(void) {
    assert(winios_surface_is_steam("c:\\program files\\steam client32\\steam.exe"));
    assert(winios_surface_is_steam("c:/steam/bin/steamwebhelper.exe"));
    assert(!winios_surface_is_steam("c:/steam.exe/game.exe"));
    assert(!winios_surface_is_steam("c:/notsteam.exe"));
    struct winios_surface_stats s = {.epoch = 7, .since = 1};
    struct winios_surface_ticket t = winios_surface_begin(&s, 42, 4096, 1.001);
    winios_surface_copied(&s, t, 1.003, 100);
    winios_surface_enqueued(&s, &t, 1.005, 1.003);
    assert(s.slots[t.slot].counts.pending == 1 && s.slots[t.slot].counts.pending_bytes == 4096);
    winios_surface_finished(&s, t, 1, 1.025, 1.030, .001, .002);
    struct winios_surface_counts *c = &s.slots[t.slot].counts;
    assert(c->received == 1 && c->queued == 1 && c->applied == 1 && !c->pending && !c->pending_bytes);
    assert(c->copied_bytes == 4096 && c->dirty_pixels == 100 && !s.slots[t.slot].in_flight);
    near(c->copy.sum, 2); near(c->prepare.sum, 2); near(c->queue.sum, 20);
    near(c->image.sum, 1); near(c->layer.sum, 2); near(c->main.sum, 5); near(c->total.sum, 29);

    // Snapshot byte ownership and pending work survive an interval boundary;
    // completed work isn't recounted in the next interval.
    t = winios_surface_begin(&s, 42, 8192, 1.5);
    winios_surface_copied(&s, t, 1.51, 100);
    winios_surface_enqueued(&s, &t, 1.52, 1.51);
    winios_surface_interval_reset(&s, 2);
    c = &s.slots[t.slot].counts;
    assert(c->pending == 1 && c->pending_bytes == 8192 && !c->received && !c->copy.n);
    winios_surface_finished(&s, t, 1, 2.1, 2.11, .002, .003);
    near(c->queue.sum, 580); near(c->total.sum, 610);
    assert(!c->pending && !c->pending_bytes && c->applied == 1);
    winios_surface_interval_reset(&s, 3);
    assert(!c->total.n && !c->applied && !c->peak_bytes);

    // Failed copies have no fake image/queue timings; skipped main blocks
    // release pending bytes without being counted as applied updates.
    t = winios_surface_begin(&s, 42, 8192, 3.1);
    winios_surface_finished(&s, t, -1, 0, 3.2, -1, -1);
    assert(c->failed == 1 && !c->image.n && !c->queue.n && !c->pending);
    t = winios_surface_begin(&s, 42, 8192, 3.3);
    winios_surface_enqueued(&s, &t, 3.4, 3.3);
    winios_surface_finished(&s, t, 0, 3.5, 3.6, -1, -1);
    assert(c->skipped == 1 && !c->applied && !c->pending && !c->pending_bytes);

    // Main = largest visible Steam-owned window, never desktop/cursor/unknown.
    struct winios_surface_slot *main = winios_surface_slot_for(&s, 100);
    main->steam = main->visible = 1; main->width = 1000; main->height = 600;
    struct winios_surface_slot *popup = winios_surface_slot_for(&s, 101);
    popup->steam = popup->visible = 1; popup->width = 500; popup->height = 200;
    struct winios_surface_slot *other = winios_surface_slot_for(&s, 102);
    other->visible = 1; other->pid = 99; other->width = other->height = 4000;
    int idx = winios_surface_main_slot(&s);
    assert(&s.slots[idx] == main);
    assert(winios_surface_role_for(main, idx, idx) == WINIOS_SURFACE_MAIN);
    assert(winios_surface_role_for(popup, (int)(popup-s.slots), idx) == WINIOS_SURFACE_STEAM_OTHER);
    assert(winios_surface_role_for(other, (int)(other-s.slots), idx) == WINIOS_SURFACE_OTHER);
    assert(winios_surface_role_for(&s.slots[0], 0, idx) == WINIOS_SURFACE_UNKNOWN);
    struct winios_surface_ticket cursor = winios_surface_begin(&s, 0, 0, 4);
    assert(winios_surface_role_for(&s.slots[cursor.slot], cursor.slot, idx) == WINIOS_SURFACE_CURSOR);
    main->visible = 0; assert(&s.slots[winios_surface_main_slot(&s)] == popup);

    // HWND reuse must not merge a destroyed window's outstanding work into
    // its replacement, including a destruction before enqueue.
    t = winios_surface_begin(&s, 555, 1024, 5);
    s.slots[t.slot].live = 0;
    winios_surface_interval_reset(&s, 5.1);
    struct winios_surface_ticket replacement = winios_surface_begin(&s, 555, 2048, 5.2);
    assert(t.slot != replacement.slot && s.slots[t.slot].serial == t.serial);
    winios_surface_enqueued(&s, &t, 5.3, 5);
    winios_surface_finished(&s, t, 1, 5.4, 5.5, 0, 0);
    assert(!s.slots[replacement.slot].counts.applied);
    winios_surface_interval_reset(&s, 6);
    assert(!s.slots[t.slot].serial);

    // Epoch invalidates delayed callbacks after stop/restart even if an HWND
    // and slot are reused. Table saturation is bounded and observable.
    struct winios_surface_stats next = {.epoch = 8};
    winios_surface_begin(&next, 555, 2048, 6);
    winios_surface_enqueued(&next, &replacement, 6.1, 6);
    winios_surface_finished(&next, replacement, 1, 6.2, 6.3, 0, 0);
    assert(!next.slots[0].counts.queued && !next.slots[0].counts.applied);
    for (int i = 1; i < WINIOS_SURFACE_STATS_SLOTS; i++) assert(winios_surface_slot_for(&next, 1000+i));
    assert(!winios_surface_slot_for(&next, 9999) && next.overflow == 1);
    struct winios_surface_counts a = {.failed = 2}, b = {.failed = 3}, sum = {0};
    winios_surface_time_add(&a.total, .002); winios_surface_time_add(&a.total, .006);
    winios_surface_time_add(&b.total, .001);
    winios_surface_counts_merge(&sum, &a); winios_surface_counts_merge(&sum, &b);
    assert(sum.failed == 5 && sum.total.n == 3);
    near(sum.total.sum, 9); near(sum.total.max, 6); near(sum.total.sum / sum.total.n, 3);
    puts("PASS production counters: stage timing, interval carry, failures, skip, window roles, HWND reuse, epochs and bounded overflow");
}
'''

# Execute the real adapter; only Wine's external owner lookup is a fixture.
adapter = source[source.index('/* Steam surface diagnostics have'):source.index('/* winios_close_desktop:')]
objc_test = r'''
#import <Foundation/Foundation.h>
#include <pthread.h>
#include <stdatomic.h>
#include <unistd.h>
#include <assert.h>
#include <mach/mach_time.h>
#include <time.h>
#include "WiniosSurfaceStats.h"
#include "steam_alloc_stats.h"
typedef void *HWND;
#define WINIOS_CENSUS_IMAGE 264
static atomic_uint owner_queries;
static double winios_now_mono(void) { return (double)clock_gettime_nsec_np(CLOCK_UPTIME_RAW) / 1e9; }
static int winios_drv_census_owner(HWND hwnd, unsigned *pid, unsigned *style) {
    atomic_fetch_add(&owner_queries, 1); *pid = 123; *style = 0; return 1;
}
static int winios_drv_process_image(unsigned pid, char *out, unsigned size) {
    snprintf(out, size, "c:/steam/steamwebhelper.exe"); return 1;
}
'''
objc_main = r'''
int main(void) { @autoreleasepool {
    fprintf(stderr, "[fixture] surface-only\n");
    winios_allocation_stats_configure(0);
    winios_surface_stats_configure(0);
    assert(winios_surface_stats_begin((void *)42, 1024).slot == -1);
    winios_surface_stats_configure(1);
    assert(!__atomic_load_n(&ios_sa_on, __ATOMIC_ACQUIRE) && !g_allocation_stats_timer);
    winios_surface_stats_window((void *)42, 800, 600, 1);
    winios_surface_stats_window((void *)42, 800, 600, 1);
    assert(atomic_load(&owner_queries) == 1);
    struct winios_surface_ticket t = winios_surface_stats_begin((void *)42, 1024);
    double copy = winios_surface_stats_copied(t, 10);
    t = winios_surface_stats_enqueue(t, copy);
    winios_surface_stats_finish(t, 1, winios_now_mono(), .001, .002);
    winios_surface_stats_window((void *)42, -1, -1, 0);
    assert(winios_surface_main_slot(&g_surface_stats) == -1);
    winios_surface_stats_window((void *)42, 800, 600, 1);
    assert(winios_surface_main_slot(&g_surface_stats) >= 0);
    // No main-queue pumping: a utility timer must still emit both active and
    // idle heartbeat intervals. This models UIKit being busy independently.
    usleep(2200000);
    winios_surface_stats_forget((void *)42);
    assert(winios_surface_main_slot(&g_surface_stats) == -1);
    winios_surface_stats_configure(0);
    assert(!g_surface_stats_timer && winios_surface_stats_begin((void *)42, 1).slot == -1);
    winios_surface_stats_configure(1);
    winios_surface_stats_finish(t, 1, winios_now_mono(), 1, 1);
    assert(!g_surface_stats.slots[0].counts.applied);
    winios_surface_stats_window((void *)42, 800, 600, 1);
    dispatch_apply(8, dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^(size_t worker) {
        for (int i = 0; i < 100; i++) {
            struct winios_surface_ticket parallel = winios_surface_stats_begin((void *)42, 4096);
            double copied = winios_surface_stats_copied(parallel, 100);
            parallel = winios_surface_stats_enqueue(parallel, copied);
            winios_surface_stats_finish(parallel, 1, winios_now_mono(), 0, 0);
        }
    });
    pthread_mutex_lock(&g_surface_stats_lock);
    assert(g_surface_stats.slots[0].counts.applied == 800 && !g_surface_stats.slots[0].counts.pending
           && !g_surface_stats.slots[0].counts.pending_bytes && !g_surface_stats.slots[0].in_flight);
    pthread_mutex_unlock(&g_surface_stats_lock);
    winios_surface_stats_configure(0);
    assert(!__atomic_load_n(&ios_sa_on, __ATOMIC_ACQUIRE));
    fprintf(stderr, "[fixture] allocation-only\n");
    winios_allocation_stats_configure(1);
    assert(__atomic_load_n(&ios_sa_on, __ATOMIC_ACQUIRE) && g_allocation_stats_timer && !g_surface_stats_timer);
    assert(winios_surface_stats_begin((void *)42, 1).slot == -1);
    struct ios_sa_request request;
    ios_sa_begin(&request, 0xe8, 0x20c, 1, 4096, 0, 0x3000, 0);
    ios_sa_end(&request, 0);
    usleep(1300000);

    fprintf(stderr, "[fixture] both-on\n");
    uint64_t allocation_epoch = ios_sa_epoch;
    winios_surface_stats_configure(1);
    assert(ios_sa_epoch == allocation_epoch && __atomic_load_n(&ios_sa_on, __ATOMIC_ACQUIRE));
    assert(g_surface_stats_timer && g_allocation_stats_timer);
    ios_sa_begin(&request, 0xe8, 0x20c, 1, 8192, 0, 0x3000, 0);
    ios_sa_end(&request, 0);
    usleep(1300000);

    fprintf(stderr, "[fixture] allocation-stopped\n");
    winios_allocation_stats_configure(0);
    assert(!__atomic_load_n(&ios_sa_on, __ATOMIC_ACQUIRE) && !g_allocation_stats_timer);
    assert(atomic_load(&g_surface_stats_on) && g_surface_stats_timer);
    ios_sa_begin(&request, 0xe8, 0x20c, 1, 4096, 0, 0x3000, 0);
    assert(!request.root);
    usleep(1300000);
    winios_surface_stats_configure(0);
    assert(!g_surface_stats_timer && !g_allocation_stats_timer);
    puts("PASS production adapter: independent off/on, once-per-window lookup, visibility, utility heartbeat, stop, restart and concurrent producers");
    puts("PASS production surface/allocation timers: all four combinations, allocation-only heartbeat without UIKit, no cross-reset and stopping allocation preserves surface sampling");
} return 0; }
'''

with tempfile.TemporaryDirectory() as directory:
    d = Path(directory)
    c = d / 'counts.c'
    c.write_text(c_test)
    exe = d / 'counts'
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(native), str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
    m = d / 'adapter.m'
    m.write_text(objc_test + '\n' + adapter + '\n' + objc_main)
    executable = d / 'adapter'
    subprocess.run(['xcrun', 'clang', '-fobjc-arc', '-fblocks', '-Wall', '-Werror', '-Wno-unused-function',
                    '-I' + str(native), '-I' + str(root / 'build/ntdll-unix'), str(m), '-framework', 'Foundation', '-o', str(executable)], check=True)
    result = subprocess.run([str(executable)], text=True, capture_output=True, check=True, timeout=15)
    print(result.stdout, end='')
    rows = [line for line in result.stderr.splitlines() if 'kind=steam-main' in line]
    assert len(rows) >= 2 and any('applied=1 ' in line for line in rows) and any('applied=0 ' in line for line in rows), result.stderr
    assert any('kind=cursor' in line for line in result.stderr.splitlines()), result.stderr
    surface_only = result.stderr.split('[fixture] surface-only\n', 1)[1].split('[fixture] allocation-only\n', 1)[0]
    allocation_only = result.stderr.split('[fixture] allocation-only\n', 1)[1].split('[fixture] both-on\n', 1)[0]
    both_on = result.stderr.split('[fixture] both-on\n', 1)[1].split('[fixture] allocation-stopped\n', 1)[0]
    stopped = result.stderr.split('[fixture] allocation-stopped\n', 1)[1]
    assert '[steam-alloc]' not in surface_only and '[steam-surface]' in surface_only
    assert '[steam-surface]' not in allocation_only and re.search(r'\[steam-alloc\].*kind=total .*requests=1 ', allocation_only)
    assert '[steam-surface]' in both_on and '[steam-alloc]' in both_on
    assert '[steam-surface]' in stopped
    assert not re.search(r'\[steam-alloc\].*kind=', stopped), 'old allocation timer must not report into stopped/new epoch'
    print('PASS adapter log: active and idle main-window intervals plus separate cursor, without main-queue execution')

sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
subprocess.run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios17.0', '-isysroot', sdk,
                '-fobjc-arc', '-fblocks', '-fsyntax-only', '-Werror=format', '-Werror=implicit-function-declaration',
                '-Wno-deprecated-declarations', str(native / 'Winios.m')], check=True)
print('PASS full production Winios.m: iPhoneOS syntax and diagnostic format checking (no product build)')

assert source.index('winios_surface_stats_window(hwnd, w, h, visible);') > source.index('void winios_window_frame(')
surface = source[source.index('int winios_surface_present('):source.index('static CALayer *g_cursor_layer;')]
assert surface.index('winios_surface_stats_enqueue') < surface.index('dispatch_async(dispatch_get_main_queue()')
assert surface.count('winios_surface_stats_finish') == 4, 'allocation failure, no compositor, filtered game window, normal/image failure'
assert 'winios_surface_stats_configure' not in source[source.index('void winios_window_census_enable('):source.index('int winios_window_census(')]
assert bridge.index('unsetenv("MADEIRA_STEAM_SURFACE_STATS")') < bridge.index('setenv(k.UTF8String, v.UTF8String, 1);')
assert bridge.index('winios_surface_stats_configure(e && *e && strcmp(e, "0"));') > bridge.index('dup2(logfd, STDERR_FILENO);')
assert len(re.findall(r'winios_surface_stats_configure\(0\);\s+g_wine_running = 0;', bridge)) == 2, 'normal and rejected-argument exits stop sampling'
assert len(re.findall(r'winios_allocation_stats_configure\(0\);\s+winios_surface_stats_configure\(0\);\s+g_wine_running = 0;', bridge)) == 2
assert bridge.index('unsetenv("MADEIRA_STEAM_ALLOC_STATS")') < bridge.index('setenv(k.UTF8String, v.UTF8String, 1);')
assert bridge.index('e = getenv("MADEIRA_STEAM_ALLOC_STATS");') > bridge.index('dup2(logfd, STDERR_FILENO);')
assert 'winios_allocation_stats_configure(e && *e && strcmp(e, "0"));' in bridge
assert 'python3 tests/host/check-steam-surface-stats.py' in workflow
print('PASS integration: independent lifecycle, all surface exits accounted for, environment precedence and checks-only workflow')
