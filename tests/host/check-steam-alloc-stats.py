#!/usr/bin/env python3
"""Run production diagnostics, public/internal wrappers and the low-first branch.

The allocator bodies beneath the wrappers are controlled fixtures; no Wine task,
guest allocator, app build or physical-device success is implied.
"""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'build/ntdll-unix/virtual_ios.c').read_text()
header_dir = root / 'build/ntdll-unix'


def function_after(marker, signature):
    start = source.index(signature, source.index(marker) + len(marker))
    brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


wrappers = '\n'.join([
    function_after('#undef allocate_virtual_memory', 'static NTSTATUS allocate_virtual_memory('),
    function_after('#undef NtAllocateVirtualMemory\n', 'NTSTATUS WINAPI NtAllocateVirtualMemory('),
    function_after('#undef NtAllocateVirtualMemoryEx\n', 'NTSTATUS WINAPI NtAllocateVirtualMemoryEx('),
])
low_start = source.index('        if (ios_wow_laa_synth && ios_wow_laa_low_first() && !base &&')
low_end = source.index('\n#endif', low_start)
low_branch = source[low_start:low_end]
fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <pthread.h>
#include <errno.h>
#include <time.h>
static _Thread_local uint64_t fake_now = 1000000000ull;
static int fake_clock(clockid_t id, struct timespec *ts) {
    (void)id; ts->tv_sec = fake_now / 1000000000ull; ts->tv_nsec = fake_now % 1000000000ull;
    errno = ERANGE; return 0; /* instrumentation must preserve caller errno */
}
#define clock_gettime fake_clock
#include "steam_alloc_stats.h"
#undef clock_gettime
#define WINAPI
typedef unsigned NTSTATUS, ULONG;
typedef uintptr_t ULONG_PTR;
typedef size_t SIZE_T;
typedef void *HANDLE, *PVOID;
typedef unsigned MEM_EXTENDED_PARAMETER;
struct fake_teb { struct { uintptr_t UniqueProcess, UniqueThread; } ClientId; };
typedef struct fake_teb TEB;
static _Thread_local TEB teb = {{0xe8, 0x20c}};
static TEB *NtCurrentTeb(void) { return &teb; }
static HANDLE NtCurrentProcess(void) { return (HANDLE)(intptr_t)-1; }
static void advance(uint64_t ns) { fake_now += ns; }
enum { NORMAL, CONFLICT_RECOVER, FINAL_CONFLICT, LOW_OK, LOW_FALLBACK_OK,
       LOW_FALLBACK_FAIL, INVALID, REMOTE, NESTED_API, NESTED_ATTEMPT };
static _Thread_local int mode, depth;
static _Thread_local unsigned attempts, low_calls, full_calls, api_calls;
static _Thread_local int lower_has_room, fallback_has_room;
static uintptr_t ios_wow_base(void) { return 0x7200000000ull; }
static int ios_wow_laa_low_first(void) { return 1; }
static int ios_wow_limits_in_window(uintptr_t a, uintptr_t b) { return a == 0 && b == 0xffffffff; }
static void *map_reserved_area(void *start, void *end, size_t size, int top_down, int prot, size_t mask) {
    (void)start; (void)size; (void)top_down; (void)prot; (void)mask;
    if ((uintptr_t)end == ios_wow_base() + 0x80000000ull) {
        low_calls++; advance(5000000); return lower_has_room ? (void *)(ios_wow_base()+0x10000) : NULL;
    }
    full_calls++; advance(7000000); return fallback_has_room ? (void *)(ios_wow_base()+0x90000000) : NULL;
}
static NTSTATUS run_low_branch(void **result) {
    struct ios_sa_fallback alloc_fallback __attribute__((cleanup(ios_sa_fallback_end))) = {0};
    int ios_wow_laa_synth = 1, top_down = 0, unix_prot = 0;
    uintptr_t limit_low = 0, limit_high = 0xffffffff, limit_2g = 0x80000000ull;
    void *base = NULL, *ptr = NULL, *start = (void *)(ios_wow_base()+0x110000), *end = (void *)(ios_wow_base()+0x100000000ull);
    size_t view_size = 0x200000, host_size = view_size, size = view_size, align_mask = 0xffff;
#define dprintf(...) ((void)0)
/* LOW_BRANCH */
#undef dprintf
    ptr = map_reserved_area(start,end,host_size,top_down,unix_prot,align_mask);
done:
    *result = ptr;
    return ptr ? 0 : 0xc0000017u;
}
static NTSTATUS allocate_virtual_memory(void **ret, SIZE_T *size, ULONG type, ULONG protect,
                                        ULONG_PTR lo, ULONG_PTR hi, ULONG_PTR align, ULONG attr);
NTSTATUS WINAPI NtAllocateVirtualMemory(HANDLE process, PVOID *ret, ULONG_PTR bits,
                                        SIZE_T *size, ULONG type, ULONG protect);
NTSTATUS WINAPI NtAllocateVirtualMemoryEx(HANDLE process, PVOID *ret, SIZE_T *size, ULONG type,
                                          ULONG protect, MEM_EXTENDED_PARAMETER *params, ULONG count);
static NTSTATUS ios_sa_allocate_impl(void **ret, SIZE_T *size, ULONG type, ULONG protect,
                                      ULONG_PTR lo, ULONG_PTR hi, ULONG_PTR align, ULONG attr) {
    (void)lo; (void)hi; (void)align; (void)attr; attempts++;
    if (mode == LOW_OK || mode == LOW_FALLBACK_OK || mode == LOW_FALLBACK_FAIL) return run_low_branch(ret);
    advance(5000000);
    if (mode == NESTED_ATTEMPT && !depth) {
        depth++; unsigned st = allocate_virtual_memory(ret,size,type,protect,0,0,0,0); depth--; return st;
    }
    if (mode == FINAL_CONFLICT || (mode == CONFLICT_RECOVER && attempts == 1)) return IOS_SA_CONFLICT;
    *ret = (void *)0x7290000000ull; return 0;
}
static NTSTATUS body(HANDLE process, PVOID *ret, SIZE_T *size, ULONG type, ULONG protect) {
    api_calls++;
    if (mode == INVALID) return 0xc000000du;
    if (mode == REMOTE) { assert(process != NtCurrentProcess()); advance(11000000); return 0; }
    if (mode == NESTED_API && !depth) {
        depth++; unsigned st = NtAllocateVirtualMemoryEx(process,ret,size,type,protect,NULL,0); depth--; return st;
    }
    unsigned st = allocate_virtual_memory(ret,size,type,protect,0,0,0,0);
    if (mode == CONFLICT_RECOVER && st) { *ret = NULL; st = allocate_virtual_memory(ret,size,type,protect,0,0,0,0); }
    advance(3000000); return st;
}
static NTSTATUS ios_sa_NtAllocateVirtualMemory_impl(HANDLE process,PVOID *ret,ULONG_PTR bits,SIZE_T *size,ULONG type,ULONG protect) {
    (void)bits; return body(process,ret,size,type,protect);
}
static NTSTATUS ios_sa_NtAllocateVirtualMemoryEx_impl(HANDLE process,PVOID *ret,SIZE_T *size,ULONG type,ULONG protect,MEM_EXTENDED_PARAMETER *params,ULONG count) {
    (void)params; (void)count; return body(process,ret,size,type,protect);
}
/* WRAPPERS */
static void reset(int choice) {
    assert(!ios_sa_current); mode = choice; attempts = low_calls = full_calls = api_calls = depth = 0;
    lower_has_room = choice == LOW_OK; fallback_has_room = choice == LOW_FALLBACK_OK;
    ios_steam_alloc_stats_configure(1, __atomic_load_n(&ios_sa_epoch,__ATOMIC_RELAXED)+1);
}
static unsigned call(unsigned ex) {
    void *ret = (void *)0x7250000000ull; size_t size = 0x200000;
    errno = EBUSY;
    unsigned st = ex ? NtAllocateVirtualMemoryEx(NtCurrentProcess(),&ret,&size,0x2000,1,NULL,0)
                     : NtAllocateVirtualMemory(NtCurrentProcess(),&ret,0,&size,0x2000,1);
    assert(errno == EBUSY && size == 0x200000);
    if (!st && mode != REMOTE) assert(ret != (void *)0x7250000000ull);
    return st;
}
static void *producer(void *arg) {
    teb.ClientId.UniqueThread = 0x300+(uintptr_t)arg; fake_now = 1000000000ull; mode = NORMAL;
    for (int i = 0; i < 200; i++) assert(!call(i&1));
    return NULL;
}
int main(void) {
    for (unsigned ex = 0; ex < 2; ex++) {
        reset(CONFLICT_RECOVER); assert(!call(ex));
        assert(ios_sa_total.requests == 1 && ios_sa_total.success == 1 && !ios_sa_total.failed);
        assert(ios_sa_total.attempts == 2 && ios_sa_total.conflicts == 1 && ios_sa_total.hinted_conflicts == 1);
        assert(ios_sa_total.recovered == 1 && ios_sa_total.retries == 1 && ios_sa_total.retry_requests == 1);
        assert(ios_sa_total.total.ns == 13000000 && ios_sa_total.attempt.ns == 10000000);
        assert(ios_sa_total.conflict.ns == 5000000 && ios_sa_total.hinted_conflict.ns == 5000000 && ios_sa_total.retry.ns == 5000000);
        assert(ios_sa_rows[0].api == ex+1 && ios_sa_rows[0].tid == 0x20c && ios_sa_rows[0].bucket == 2);
        reset(FINAL_CONFLICT); assert(call(ex) == IOS_SA_CONFLICT);
        assert(ios_sa_total.failed == 1 && ios_sa_total.final_conflict == 1 && !ios_sa_total.recovered);
        reset(LOW_OK); assert(!call(ex));
        assert(low_calls == 1 && !full_calls && ios_sa_total.low_try == 1 && ios_sa_total.low_success == 1);
        assert(ios_sa_total.low.ns == 5000000 && !ios_sa_total.fallback.n && ios_sa_total.total.ns == 8000000);
        reset(LOW_FALLBACK_OK); assert(!call(ex));
        assert(low_calls == 1 && full_calls == 1 && ios_sa_total.low_miss == 1 && ios_sa_total.fallback_success == 1);
        assert(!ios_sa_total.fallback_failed && ios_sa_total.low.ns == 5000000 && ios_sa_total.fallback.ns == 7000000);
        assert(ios_sa_total.attempt.ns == 12000000 && ios_sa_total.total.ns == 15000000);
        reset(LOW_FALLBACK_FAIL); assert(call(ex) == 0xc0000017u);
        assert(ios_sa_total.fallback_failed == 1 && ios_sa_total.failed == 1 && !ios_sa_total.fallback_success);
        reset(INVALID); assert(call(ex) == 0xc000000du);
        assert(ios_sa_total.failed == 1 && !ios_sa_total.attempts);
        reset(NESTED_API); assert(!call(ex));
        assert(api_calls == 2 && ios_sa_total.requests == 1 && ios_sa_total.attempts == 1);
        reset(NESTED_ATTEMPT); assert(!call(ex));
        assert(attempts == 2 && ios_sa_total.attempts == 1 && ios_sa_total.attempt.ns == 10000000);
        reset(NORMAL); ios_steam_alloc_stats_configure(0,ios_sa_epoch+1); assert(!call(ex));
        assert(attempts == 1 && !ios_sa_total.requests && !ios_sa_current);
    }
    reset(REMOTE); void *ret = NULL; size_t size = 100;
    assert(!NtAllocateVirtualMemory((void *)123,&ret,0,&size,0x2000,1));
    assert(ios_sa_total.remote == 1 && !ios_sa_total.attempts && ios_sa_total.total.ns == 11000000);

    // A request spanning an interval is attributed once, on completion.
    reset(NORMAL); struct ios_sa_request pending;
    ios_sa_begin(&pending,0xe8,0x20c,1,123,0,0x2000,0); advance(1500000000);
    ios_steam_alloc_stats_report(ios_sa_epoch); assert(!ios_sa_total.requests);
    ios_sa_end(&pending,0); assert(ios_sa_total.requests == 1 && ios_sa_total.total.ns == 1500000000);
    // Stop/restart discards a late request without contaminating the new session.
    reset(NORMAL); ios_sa_begin(&pending,0xe8,0x20c,1,123,0,0x2000,0);
    ios_steam_alloc_stats_configure(0,ios_sa_epoch+1); ios_steam_alloc_stats_configure(1,ios_sa_epoch+1);
    ios_sa_end(&pending,IOS_SA_CONFLICT); assert(!ios_sa_total.requests && !ios_sa_current);
    uint64_t epoch = ios_sa_epoch; ios_steam_alloc_stats_report(epoch-1); assert(ios_sa_epoch == epoch);

    // Bounded attribution overflow never loses totals, including request size.
    reset(NORMAL);
    for (unsigned i = 0; i < IOS_SA_SLOTS+3; i++) {
        ios_sa_begin(&pending,0xe8,1000+i,1,100+i,0,0x2000,0); advance(1000); ios_sa_end(&pending,0);
    }
    assert(ios_sa_overflow == 3 && ios_sa_total.requests == IOS_SA_SLOTS+3 && ios_sa_unlisted.requests == 3);
    assert(ios_sa_total.min_size == 100 && ios_sa_total.max_size == 100+IOS_SA_SLOTS+2);
    advance(1000000000); ios_steam_alloc_stats_report(ios_sa_epoch);
    assert(!ios_sa_total.requests && !ios_sa_unlisted.requests && !ios_sa_overflow);
    advance(1000000000); ios_steam_alloc_stats_report(ios_sa_epoch);

    reset(NORMAL); pthread_t workers[4];
    for (uintptr_t i=0;i<4;i++) assert(!pthread_create(&workers[i],NULL,producer,(void *)i));
    for (unsigned i=0;i<4;i++) assert(!pthread_join(workers[i],NULL));
    assert(ios_sa_total.requests == 800 && ios_sa_total.success == 800 && ios_sa_total.attempts == 800 && !ios_sa_total.failed);
    assert(ios_sa_total.total.ns == 800ull*8000000);
    ios_steam_alloc_stats_configure(0,ios_sa_epoch+1);
    puts("PASS production allocation stats: both API wrappers, unchanged results/errno, conflict recovery, final failure, low-first and fallback timing, nested attempts, off/on, interval carry, stale epochs, bounded attribution and concurrent producers");
}
'''.replace('/* LOW_BRANCH */', low_branch).replace('/* WRAPPERS */', wrappers)

with tempfile.TemporaryDirectory() as folder:
    d = Path(folder); c = d / 'alloc.c'; exe = d / 'alloc'
    c.write_text(fixture)
    subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-variable',
                    '-fsanitize=address,undefined','-pthread','-I'+str(header_dir),str(c),'-o',str(exe)],check=True)
    result = subprocess.run([str(exe)],text=True,capture_output=True,check=True,timeout=30)
    print(result.stdout,end='')
    rows = [x for x in result.stderr.splitlines() if 'kind=total ' in x]
    assert any('requests=0 ' in x for x in rows)
    assert any('requests=131 ' in x and 'overflow=3 ' in x for x in rows)
    assert any('kind=remainder ' in x and 'requests=123 ' in x for x in result.stderr.splitlines())
    detail = [x for x in result.stderr.splitlines() if 'kind=thread-size ' in x]
    assert len(detail) == 8, result.stderr
    print('PASS production reporter: idle heartbeat, exact totals despite overflow, top-eight cap and complete remainder')

assert '#include "steam_alloc_stats.h"' in source
assert 'struct ios_sa_fallback alloc_fallback __attribute__((cleanup(ios_sa_fallback_end))) = {0};' in source
assert 'ios_sa_fallback_begin( &alloc_fallback );' in low_branch
assert low_branch.count('map_reserved_area(') == 1
winios = (root / 'app/Madeira/Winios/Winios.m').read_text()
assert 'ios_steam_alloc_stats_configure(enabled, epoch);' in winios and 'ios_steam_alloc_stats_report(epoch);' in winios
assert 'python3 tests/host/check-steam-alloc-stats.py' in (root / '.github/workflows/build.yml').read_text()
print('PASS integration: same independent Steam switch and utility timer; allocation search and return policies unchanged')
