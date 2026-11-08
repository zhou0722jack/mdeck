/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "steam_cef_guard.h"
#include <pthread.h>
#include <stdio.h>
#include <string.h>

#define CEF_ADDRESS_FAILURE 0xc0000017u
#define CEF_INIT_BREAKPOINT 0x80000003u
#define CEF_FAIL_FAST       0xc0000409u
#define CEF_X64            0x8664u
#define CEF_RESERVE        0x2000u
#define CEF_COMMIT         0x1000u
#define CEF_ATTEMPTS       32

/* The callback carries only an opaque launch ID, never a credential/path. */
extern void madeira_steam_cef_address_failure(const char *run) __attribute__((weak));
extern void madeira_steam_initial_window_failure(const char *run) __attribute__((weak));
static pthread_mutex_t guard_lock = PTHREAD_MUTEX_INITIALIZER;
static char current_run[37];
static uintptr_t failed_owners[CEF_ATTEMPTS];
static unsigned char failed_kinds[CEF_ATTEMPTS];
static unsigned int owner_count;
static int stopped;
static int client_window_notified;

int ios_steam_cef_valid_run(const char *run)
{
    size_t i;
    if (!run || strnlen(run, 37) != 36) return 0;
    for (i = 0; i < 36; i++)
    {
        char c = run[i];
        if (i == 8 || i == 13 || i == 18 || i == 23) { if (c != '-') return 0; }
        else if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'))) return 0;
    }
    return 1;
}

static int win64_image_matches(const uint16_t *image, size_t chars, unsigned int machine,
                               const char *expected, size_t expected_chars)
{
    size_t i, start = 0;
    if (!image || machine != CEF_X64) return 0;
    if (chars >= 4 && image[0] == '\\' && image[1] == '?' && image[2] == '?' && image[3] == '\\') start = 4;
    if (chars - start != expected_chars) return 0;
    for (i = 0; i < expected_chars; i++)
    {
        uint16_t c = image[start + i];
        if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
        if (c == '/') c = '\\';
        if (c != (uint16_t)expected[i]) return 0;
    }
    return 1;
}

int ios_steam_cef_win64_helper(const uint16_t *image, size_t chars, unsigned int machine)
{
    static const char expected[] = "c:\\program files\\steam client\\bin\\cef\\cef.win64\\steamwebhelper.exe";
    return win64_image_matches(image, chars, machine, expected, sizeof(expected) - 1);
}

/* Called with guard_lock held. The app changes this UUID before each launch. */
static void select_run(const char *run)
{
    if (!strcmp(current_run, run)) return;
    memcpy(current_run, run, sizeof(current_run));
    memset(failed_owners, 0, sizeof(failed_owners));
    memset(failed_kinds, 0, sizeof(failed_kinds));
    owner_count = 0;
    stopped = 0;
    client_window_notified = 0;
}

/* Steam's updater reports this exact fatal status after its initial window
 * fails. Explorer/services may stay alive, so whole-session exit cannot be
 * used to stop waiting for a Steam frame. This is independent of CEF failures. */
static void steam_initial_window_exit(const char *run, uintptr_t owner, const uint16_t *image,
                                      size_t chars, unsigned int machine, unsigned int status)
{
    static const char expected[] = "c:\\program files\\steam client\\steam.exe";
    char notification[37];
    int notify = 0;
    if (status != 0xffffff98u || !owner || !ios_steam_cef_valid_run(run) ||
        !win64_image_matches(image, chars, machine, expected, sizeof(expected) - 1)) return;
    pthread_mutex_lock(&guard_lock);
    select_run(run);
    if (!client_window_notified)
    {
        client_window_notified = 1;
        memcpy(notification, run, sizeof(notification));
        notify = 1;
    }
    pthread_mutex_unlock(&guard_lock);
    if (notify)
    {
        fprintf(stderr, "[steam-startup] canonical Win64 Steam exited with -104 before update UI initialization\n");
        if (madeira_steam_initial_window_failure) madeira_steam_initial_window_failure(notification);
    }
}

void ios_steam_cef_allocation_result(const char *run, uintptr_t owner, const uint16_t *image, size_t chars,
                                     unsigned int machine, uint64_t requested, unsigned int type, unsigned int status)
{
    unsigned int i, kind = requested > (16ull << 30) + 0x10000 ? 2u : 1u;
    /* Failed random hints are normal allocator probes (c0000018), not this
     * fault. A successful retry clears this owner's failed reserve record. */
    if (!ios_steam_cef_valid_run(run) || !owner || !ios_steam_cef_win64_helper(image, chars, machine) ||
        !(type & CEF_RESERVE) || (type & CEF_COMMIT) ||
        requested < (16ull << 30) || requested > (32ull << 30)) return;
    if (status && status != CEF_ADDRESS_FAILURE) return;
    pthread_mutex_lock(&guard_lock);
    select_run(run);
    for (i = 0; i < owner_count; i++) if (failed_owners[i] == owner) break;
    if (!status)
    {
        if (i < owner_count)
        {
            failed_kinds[i] &= (unsigned char)~kind;
            if (!failed_kinds[i])
            {
                owner_count--;
                failed_owners[i] = failed_owners[owner_count];
                failed_kinds[i] = failed_kinds[owner_count];
            }
        }
    }
    else if (i < owner_count) failed_kinds[i] |= (unsigned char)kind;
    else if (owner_count < CEF_ATTEMPTS)
    {
        failed_owners[owner_count] = owner;
        failed_kinds[owner_count++] = (unsigned char)kind;
    }
    pthread_mutex_unlock(&guard_lock);
}

void ios_steam_cef_process_exit(const char *run, uintptr_t owner, const uint16_t *image, size_t chars,
                                unsigned int machine, unsigned int status)
{
    unsigned int i;
    char notification[37];
    int notify = 0;
    steam_initial_window_exit(run, owner, image, chars, machine, status);
    if (!ios_steam_cef_valid_run(run) || !owner || !ios_steam_cef_win64_helper(image, chars, machine)) return;
    pthread_mutex_lock(&guard_lock);
    select_run(run);
    for (i = 0; i < owner_count; i++) if (failed_owners[i] == owner) break;
    if (i < owner_count && !stopped &&
        (status == CEF_INIT_BREAKPOINT || status == CEF_ADDRESS_FAILURE || status == CEF_FAIL_FAST))
    {
        stopped = 1;
        memcpy(notification, current_run, sizeof(notification));
        notify = 1;
    }
    /* A PEB address can be reused. A normal/unrelated exit must not leave
     * failed allocation history attached to its next occupant. */
    if (i < owner_count)
    {
        owner_count--;
        failed_owners[i] = failed_owners[owner_count];
        failed_kinds[i] = failed_kinds[owner_count];
    }
    pthread_mutex_unlock(&guard_lock);
    if (notify)
    {
        fprintf(stderr, "[steam-cef] Win64 helper exited after a large address reservation failed; automatic restarts stopped for this session\n");
        if (madeira_steam_cef_address_failure) madeira_steam_cef_address_failure(notification);
    }
}

int ios_steam_cef_spawn_blocked(const char *run, const uint16_t *image, size_t chars,
                               unsigned int machine, int auxiliary)
{
    int block;
    if (auxiliary || !ios_steam_cef_valid_run(run) || !ios_steam_cef_win64_helper(image, chars, machine)) return 0;
    pthread_mutex_lock(&guard_lock);
    select_run(run);
    block = stopped;
    pthread_mutex_unlock(&guard_lock);
    return block;
}
