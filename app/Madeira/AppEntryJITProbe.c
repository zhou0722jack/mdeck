/* SPDX-License-Identifier: GPL-3.0-or-later
 * Pre-Wine A/B/C probe: borrow eight bytes in existing memory, execute,
 * restore original bytes. No extra allocation, reservation or debugger call. */
#include "JITAllocator.h"
#include <TargetConditionals.h>
#include <mach/mach.h>
#include <mach/vm_map.h>
#include <sys/ucontext.h>
#include <libkern/OSCacheControl.h>
#include <pthread.h>
#include <signal.h>
#include <setjmp.h>
#include <string.h>

#define ENTRY_PROBE_BYTES 8
#define ENTRY_PROBE_REGIONS 3

#if defined(__aarch64__) && !TARGET_OS_SIMULATOR
static pthread_mutex_t probe_lock = PTHREAD_MUTEX_INITIALIZER;
static JITEntryProbeRegion probe_regions[ENTRY_PROBE_REGIONS];
static JITEntryProbeReport probe_report;
static uint32_t probe_original[ENTRY_PROBE_REGIONS][2];
static unsigned probe_dirty_mask;
static int probe_bound, probe_sealed, probe_cleanup_failed;
static _Thread_local sigjmp_buf probe_return;
static _Thread_local volatile uintptr_t probe_pc, probe_access_lo;
static const int probe_signals[] = { SIGBUS, SIGSEGV, SIGILL };
static struct sigaction probe_previous[3];

static void probe_fault(int signal, siginfo_t *info, void *context)
{
    ucontext_t *uc = context;
    uintptr_t pc = uc->uc_mcontext->__ss.__pc;
    uintptr_t address = info ? (uintptr_t)info->si_addr : 0;
    if ((probe_pc && pc >= probe_pc && pc - probe_pc < ENTRY_PROBE_BYTES) ||
        (probe_access_lo && address >= probe_access_lo && address - probe_access_lo < ENTRY_PROBE_BYTES)) {
        probe_pc = probe_access_lo = 0;
        siglongjmp(probe_return, 1);
    }
    /* Only this thread's borrowed bytes/instructions are ours. Preserve
     * unrelated faults, previous flags and one-shot signal semantics. */
    for (unsigned i = 0; i < 3; i++) if (probe_signals[i] == signal) {
        struct sigaction *previous = &probe_previous[i];
        if (previous->sa_handler == SIG_IGN) return;
        if (previous->sa_handler == SIG_DFL) {
            sigaction(signal, previous, NULL);
            raise(signal);
        } else {
            if (previous->sa_flags & SA_RESETHAND) {
                struct sigaction reset;
                memset(&reset, 0, sizeof(reset));
                reset.sa_handler = SIG_DFL;
                sigemptyset(&reset.sa_mask);
                sigaction(signal, &reset, NULL);
            }
            if (previous->sa_flags & SA_SIGINFO) previous->sa_sigaction(signal, info, context);
            else previous->sa_handler(signal);
        }
        return;
    }
}

static int probe_protection(uintptr_t address, vm_prot_t required)
{
    vm_address_t start = address;
    vm_size_t size = 0;
    vm_region_basic_info_data_64_t info;
    mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
    mach_port_t object = MACH_PORT_NULL;
    kern_return_t result = vm_region_64(mach_task_self(), &start, &size, VM_REGION_BASIC_INFO_64,
                                       (vm_region_info_t)&info, &count, &object);
    if (object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), object);
    return result == KERN_SUCCESS && start <= address && size >= ENTRY_PROBE_BYTES &&
        address - start <= size - ENTRY_PROBE_BYTES && (info.protection & required) == required;
}

static int probe_overlap(uintptr_t a, size_t na, uintptr_t b, size_t nb)
{
    return a < b + nb && b < a + na;
}

static int probe_restore(unsigned region)
{
    if (!(probe_dirty_mask & (1u << region))) return 1;
    const JITEntryProbeRegion *r = &probe_regions[region];
    const uintptr_t rw = r->rw + r->size - ENTRY_PROBE_BYTES;
    const uintptr_t rx = r->rx + r->size - ENTRY_PROBE_BYTES;
    if (!probe_protection(rw, VM_PROT_READ | VM_PROT_WRITE)) return 0;
    if (sigsetjmp(probe_return, 1) != 0) return 0;
    probe_access_lo = rw;
    memcpy((void *)rw, probe_original[region], ENTRY_PROBE_BYTES);
    sys_dcache_flush((void *)rw, ENTRY_PROBE_BYTES);
    sys_icache_invalidate((void *)rx, ENTRY_PROBE_BYTES);
    if (memcmp((const void *)rw, probe_original[region], ENTRY_PROBE_BYTES)) {
        probe_access_lo = 0;
        return 0;
    }
    probe_access_lo = rx;
    if (!probe_protection(rx, VM_PROT_READ) || memcmp((const void *)rx, probe_original[region], ENTRY_PROBE_BYTES)) {
        probe_access_lo = 0;
        return 0;
    }
    probe_access_lo = 0;
    probe_dirty_mask &= ~(1u << region);
    return 1;
}

#ifndef MADEIRA_ENTRY_PROBE_EXECUTE
#define MADEIRA_ENTRY_PROBE_EXECUTE(address) (((int64_t (*)(void))(address))())
#endif

static int64_t probe_run(unsigned region)
{
    const JITEntryProbeRegion *r = &probe_regions[region];
    const uintptr_t rx = r->rx + r->size - ENTRY_PROBE_BYTES;
    const uintptr_t rw = r->rw + r->size - ENTRY_PROBE_BYTES;
    const uint32_t code[] = { 0xD2800540u, 0xD65F03C0u }; /* mov x0,#42; ret */
    int64_t result = -1;
    if (!probe_protection(rx, VM_PROT_READ | VM_PROT_EXECUTE) ||
        !probe_protection(rw, VM_PROT_READ | VM_PROT_WRITE)) return result;
    if (sigsetjmp(probe_return, 1) == 0) {
        probe_access_lo = rw;
        memcpy(probe_original[region], (const void *)rw, ENTRY_PROBE_BYTES);
        probe_dirty_mask |= 1u << region;
        memcpy((void *)rw, code, sizeof(code));
        sys_dcache_flush((void *)rw, sizeof(code));
        sys_icache_invalidate((void *)rx, sizeof(code));
        probe_access_lo = rx;
        if (!memcmp((const void *)rx, code, sizeof(code))) {
            probe_access_lo = 0;
            probe_pc = rx;
            result = MADEIRA_ENTRY_PROBE_EXECUTE((void *)rx);
        }
    } else { result = -3; }
    probe_pc = probe_access_lo = 0;
    if (!probe_restore(region)) { probe_cleanup_failed = 1; result = -4; }
    return result;
}
#endif

int64_t jit_entry_probe_bind(const JITEntryProbeRegion *regions, size_t count)
{
#if defined(__aarch64__) && !TARGET_OS_SIMULATOR
    if (!regions || count != ENTRY_PROBE_REGIONS) return -6;
    if (pthread_mutex_trylock(&probe_lock)) return -5;
    int64_t result = -6;
    if (probe_bound) {
        result = memcmp(probe_regions, regions, sizeof(probe_regions)) ? -6 : 0;
        goto done; /* An idempotent bind never clears probe_sealed. */
    }
    if (probe_sealed) goto done;
    unsigned available = 0;
    for (unsigned i = 0; i < ENTRY_PROBE_REGIONS; i++) {
        const JITEntryProbeRegion *r = &regions[i];
        if (!r->rx && !r->rw && !r->size) continue;
        if (!r->rx || !r->rw || r->size < 0x4000 ||
            ((r->rx | r->rw | r->size) & 0x3fff) ||
            r->rx > UINTPTR_MAX - r->size || r->rw > UINTPTR_MAX - r->size ||
            probe_overlap(r->rx, r->size, r->rw, r->size)) goto done;
        for (unsigned j = 0; j < i; j++) if (available & (1u << j)) {
            const JITEntryProbeRegion *s = &regions[j];
            if (probe_overlap(r->rx, r->size, s->rx, s->size) ||
                probe_overlap(r->rw, r->size, s->rw, s->size) ||
                probe_overlap(r->rx, r->size, s->rw, s->size) ||
                probe_overlap(r->rw, r->size, s->rx, s->size)) goto done;
        }
        available |= 1u << i;
    }
    if (!(available & 1u)) goto done;
    memcpy(probe_regions, regions, sizeof(probe_regions));
    memset(&probe_report, 0, sizeof(probe_report));
    probe_report.available_mask = available;
    probe_bound = 1;
    result = 0;
done:
    pthread_mutex_unlock(&probe_lock);
    return result;
#else
    (void)regions; (void)count;
    return -6;
#endif
}

void jit_entry_probe_copy_report(JITEntryProbeReport *report)
{
    if (!report) return;
    memset(report, 0, sizeof(*report));
#if defined(__aarch64__) && !TARGET_OS_SIMULATOR
    pthread_mutex_lock(&probe_lock);
    *report = probe_report;
    pthread_mutex_unlock(&probe_lock);
#endif
}

int64_t jit_entry_probe_once(void)
{
#if defined(__aarch64__) && !TARGET_OS_SIMULATOR
    if (pthread_mutex_trylock(&probe_lock)) return -5;
    int64_t result = -6;
    if (!probe_bound || probe_sealed) goto done;
    if (probe_cleanup_failed) { result = -4; goto done; }
    probe_report.tested_mask = probe_report.passed_mask = 0;
    probe_report.a = probe_report.b = probe_report.c = 0;
    uint32_t flags = 0;
    if (!jit_cs_status(&flags) || !(flags & 0x10000000u)) { result = -2; goto done; }
    struct sigaction handler;
    memset(&handler, 0, sizeof(handler));
    handler.sa_sigaction = probe_fault;
    sigemptyset(&handler.sa_mask);
    unsigned installed = 0;
    for (; installed < 3; installed++) {
        if (sigaction(probe_signals[installed], NULL, &probe_previous[installed])) break;
        handler.sa_mask = probe_previous[installed].sa_mask;
        handler.sa_flags = SA_SIGINFO | (probe_previous[installed].sa_flags & (SA_ONSTACK | SA_NODEFER | SA_RESTART));
        if (sigaction(probe_signals[installed], &handler, NULL)) break;
    }
    result = -1;
    if (installed == 3) {
        result = probe_report.available_mask == 7 ? 42 : 1;
        for (unsigned i = 0; i < ENTRY_PROBE_REGIONS; i++) if (probe_report.available_mask & (1u << i)) {
            int64_t value = probe_run(i);
            probe_report.tested_mask |= 1u << i;
            if (i == 0) probe_report.a = value;
            else if (i == 1) probe_report.b = value;
            else probe_report.c = value;
            if (value == 42) probe_report.passed_mask |= 1u << i;
            else if (result >= 0 || value == -4) result = value < 0 ? value : -1;
            if (probe_cleanup_failed) break;
        }
    }
    for (unsigned i = 0; i < installed; i++) {
        struct sigaction now;
        if (!sigaction(probe_signals[i], NULL, &now) && (now.sa_flags & SA_SIGINFO) && now.sa_sigaction == probe_fault)
            sigaction(probe_signals[i], &probe_previous[i], NULL);
    }
done:
    pthread_mutex_unlock(&probe_lock);
    return result;
#else
    return -6;
#endif
}

int64_t jit_entry_probe_release(void)
{
#if defined(__aarch64__) && !TARGET_OS_SIMULATOR
    if (pthread_mutex_trylock(&probe_lock)) return -5;
    probe_sealed = 1;
    int64_t result = probe_cleanup_failed || probe_dirty_mask ? -4 : 0;
    pthread_mutex_unlock(&probe_lock);
    return result;
#else
    return 0;
#endif
}
