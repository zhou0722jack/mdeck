/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef MDECK_STEAM_CEF_POOLS_H
#define MDECK_STEAM_CEF_POOLS_H
#include <stddef.h>
#include <stdint.h>

int ios_steam_cef_pa126_image(const unsigned char *mapped, size_t size);
void ios_steam_cef_pool_image(const char *run, uintptr_t owner, const uint16_t *image, size_t chars,
                              unsigned int machine, const unsigned char *mapped, size_t size);
void ios_steam_cef_pool_forget(const char *run, uintptr_t owner);
/* The callback must reserve exactly base/size without replacing another view.
 * It returns the actual backend status; no shortened or soft reservation. */
typedef unsigned int (*ios_steam_cef_fixed_reserve)(void *context, uint64_t base, uint64_t size);
int ios_steam_cef_pool_reserve(const char *run, uintptr_t owner, const uint16_t *image, size_t chars,
                              unsigned int machine, uint64_t hint, uint64_t size, unsigned int type,
                              unsigned int protect, uint64_t host_limit, ios_steam_cef_fixed_reserve reserve,
                              void *context, uint64_t *placed);
#endif
