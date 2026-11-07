/* SPDX-License-Identifier: GPL-3.0-or-later
 * Independent pre-Wine scratch pair: prepare once, wipe code every round,
 * release at Wine handoff. Never borrows or frees the production pool. */
#include "JITAllocator.h"
#include <TargetConditionals.h>
#include <mach/mach.h>
#include <mach/vm_map.h>
#include <sys/sysctl.h>
#include <sys/ucontext.h>
#include <libkern/OSCacheControl.h>
#include <pthread.h>
#include <signal.h>
#include <setjmp.h>
#include <string.h>
#include <unistd.h>
#include <stdio.h>

#define ENTRY_PROBE_BYTES 0x4000

#if defined(__aarch64__) && !TARGET_OS_SIMULATOR
static pthread_mutex_t probe_lock = PTHREAD_MUTEX_INITIALIZER;
static void *scratch_rx;
static vm_address_t scratch_rw;
static int scratch_writable;
static int scratch_cleanup_failed;
static _Thread_local sigjmp_buf probe_return;
static _Thread_local volatile uintptr_t probe_pc;
static const int probe_signals[] = { SIGBUS, SIGSEGV, SIGILL };
static struct sigaction probe_previous[3];

static void probe_fault(int signal, siginfo_t *info, void *context) {
    ucontext_t *uc = context;
    uintptr_t pc = uc->uc_mcontext->__ss.__pc;
    if (probe_pc && pc >= probe_pc && pc < probe_pc + 8) {
        probe_pc = 0;
        siglongjmp(probe_return, 1);
    }
    /* Only our two generated instructions belong to this handler. UIKit and
     * other threads retain the previous signal action and honest crash path. */
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

static int probe_debugger_attached(void) {
    struct kinfo_proc process;
    memset(&process, 0, sizeof(process));
    size_t size = sizeof(process);
    int mib[] = { CTL_KERN, KERN_PROC, KERN_PROC_PID, getpid() };
    return sysctl(mib, 4, &process, &size, NULL, 0) == 0 && (process.kp_proc.p_flag & P_TRACED);
}

static int probe_protection(void *address, vm_prot_t required) {
    vm_address_t start = (vm_address_t)address;
    vm_size_t size = 0;
    vm_region_basic_info_data_64_t info;
    mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
    mach_port_t object = MACH_PORT_NULL;
    kern_return_t result = vm_region_64(mach_task_self(), &start, &size, VM_REGION_BASIC_INFO_64,
                                        (vm_region_info_t)&info, &count, &object);
    if (object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), object);
    return result == KERN_SUCCESS && start <= (vm_address_t)address &&
        (vm_address_t)address - start + ENTRY_PROBE_BYTES <= size && (info.protection & required) == required;
}

static void probe_wipe(void) {
    if (scratch_rw && scratch_writable) {
        memset((void *)scratch_rw, 0, ENTRY_PROBE_BYTES);
        sys_dcache_flush((void *)scratch_rw, ENTRY_PROBE_BYTES);
        if (scratch_rx) sys_icache_invalidate(scratch_rx, ENTRY_PROBE_BYTES);
    }
}

static int64_t probe_release_locked(void) {
    if (scratch_cleanup_failed) return -4;
    probe_wipe();
    const mach_port_t task = mach_task_self();
    if (scratch_rw && vm_deallocate(task, scratch_rw, ENTRY_PROBE_BYTES) != KERN_SUCCESS) scratch_cleanup_failed = 1;
    if (scratch_rx && vm_deallocate(task, (vm_address_t)scratch_rx, ENTRY_PROBE_BYTES) != KERN_SUCCESS) scratch_cleanup_failed = 1;
    scratch_rw = 0;
    scratch_rx = NULL;
    scratch_writable = 0;
    return scratch_cleanup_failed ? -4 : 0;
}

#ifndef MADEIRA_ENTRY_PROBE_EXECUTE
#define MADEIRA_ENTRY_PROBE_EXECUTE(address) (((int64_t (*)(void))(address))())
#endif
#endif

int64_t jit_entry_probe_once(void) {
#if defined(__aarch64__) && !TARGET_OS_SIMULATOR
    if (pthread_mutex_trylock(&probe_lock)) return -5;
    uint32_t flags = 0;
    if (!jit_cs_status(&flags) || !(flags & 0x10000000u) || !probe_debugger_attached()) {
        pthread_mutex_unlock(&probe_lock);
        return -2;
    }
    const uint32_t code[] = { 0xD2800540u, 0xD65F03C0u }; /* mov x0,#42; ret */
    const mach_port_t task = mach_task_self();
    vm_prot_t current = 0, maximum = 0;
    int64_t result = -1;
    if (scratch_cleanup_failed) { pthread_mutex_unlock(&probe_lock); return -4; }
    if (!scratch_rx) {
        // Exactly one debugger transaction while waiting at the frontend.
        // Repeated BRKs can suspend the entire task when StikDebug is no
        // longer servicing its background debug session. A worker queue and
        // an in-process timeout cannot recover a task-wide debugger stop.
        jit_arm_trap_fallback();
        fprintf(stderr, "[jit-entry] scratch prepare begin: one debugger request, 16KiB\n");
        scratch_rx = jit26_prepare_region(NULL, ENTRY_PROBE_BYTES);
        fprintf(stderr, "[jit-entry] scratch prepare returned: %s\n", scratch_rx ? "allocated" : "failed");
        if (!scratch_rx) goto done;
        if (vm_remap(task, &scratch_rw, ENTRY_PROBE_BYTES, 0, VM_FLAGS_ANYWHERE, task, (vm_address_t)scratch_rx,
                     FALSE, &current, &maximum, VM_INHERIT_NONE) != KERN_SUCCESS) goto done;
        if (scratch_rw == (vm_address_t)scratch_rx) { scratch_rw = 0; goto done; }
        if (vm_protect(task, scratch_rw, ENTRY_PROBE_BYTES, FALSE, VM_PROT_READ | VM_PROT_WRITE) != KERN_SUCCESS ||
            !probe_protection((void *)scratch_rw, VM_PROT_READ | VM_PROT_WRITE)) goto done;
        scratch_writable = 1;
    }
    memcpy((void *)scratch_rw, code, sizeof(code));
    sys_dcache_flush((void *)scratch_rw, sizeof(code));
    sys_icache_invalidate(scratch_rx, sizeof(code));
    if (!probe_protection(scratch_rx, VM_PROT_READ | VM_PROT_EXECUTE) || memcmp(scratch_rx, code, sizeof(code))) goto done;

    struct sigaction handler;
    memset(&handler, 0, sizeof(handler));
    handler.sa_sigaction = probe_fault;
    handler.sa_flags = SA_SIGINFO;
    sigemptyset(&handler.sa_mask);
    unsigned installed = 0;
    for (; installed < 3; installed++) {
        if (sigaction(probe_signals[installed], NULL, &probe_previous[installed])) break;
        handler.sa_mask = probe_previous[installed].sa_mask;
        handler.sa_flags = SA_SIGINFO | (probe_previous[installed].sa_flags & (SA_ONSTACK | SA_NODEFER | SA_RESTART));
        if (sigaction(probe_signals[installed], &handler, NULL)) break;
    }
    if (installed == 3) {
        if (sigsetjmp(probe_return, 1) == 0) {
            probe_pc = (uintptr_t)scratch_rx;
            result = MADEIRA_ENTRY_PROBE_EXECUTE(scratch_rx);
        } else {
            result = -3;
        }
        probe_pc = 0;
    }
    for (unsigned i = 0; i < installed; i++) {
        struct sigaction now;
        if (!sigaction(probe_signals[i], NULL, &now) && (now.sa_flags & SA_SIGINFO) && now.sa_sigaction == probe_fault)
            sigaction(probe_signals[i], &probe_previous[i], NULL);
    }
done:
    probe_wipe();
    if (result != 42 && probe_release_locked() != 0) result = -4;
    pthread_mutex_unlock(&probe_lock);
    return result;
#else
    return -1;
#endif
}

int64_t jit_entry_probe_release(void) {
#if defined(__aarch64__) && !TARGET_OS_SIMULATOR
    if (pthread_mutex_trylock(&probe_lock)) return -5;
    int64_t result = probe_release_locked();
    pthread_mutex_unlock(&probe_lock);
    return result;
#else
    return 0;
#endif
}
