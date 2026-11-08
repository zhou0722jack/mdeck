/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef MDECK_STEAM_CEF_GUARD_H
#define MDECK_STEAM_CEF_GUARD_H

#include <stddef.h>
#include <stdint.h>

/* Native-only failure bookkeeping. Does not change any allocation result. */
int ios_steam_cef_valid_run(const char *run);
int ios_steam_cef_win64_helper(const uint16_t *image, size_t chars, unsigned int machine);
void ios_steam_cef_allocation_result(const char *run, uintptr_t owner, const uint16_t *image, size_t chars,
                                     unsigned int machine, uint64_t requested, unsigned int type, unsigned int status);
void ios_steam_cef_process_exit(const char *run, uintptr_t owner, const uint16_t *image, size_t chars,
                                unsigned int machine, unsigned int status);
int ios_steam_cef_spawn_blocked(const char *run, const uint16_t *image, size_t chars,
                               unsigned int machine, int auxiliary);

#endif
