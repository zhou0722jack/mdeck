/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "steam_cef_pools.h"
#include "steam_cef_guard.h"
#include <pthread.h>
#include <stdio.h>
#include <string.h>

/* Valve bins_cef_win64.zip.0bad5abe29375d80e5bb0eedf714329369140164:
 * chrome_elf.dll 126.0.6478.183, SHA256
 * 6358830f96f36efa7516b3277cf69c1f132f97d4d93c365ccf061a7cf11e1e39.
 * Match relocated-image-invariant code plus PE identity. No binary patching. */
static const unsigned char pa126_allocate_code[64] = {
    0x10,0x00,0x00,0x74,0x23,0x48,0x8d,0x0d,0x7a,0x17,0x10,0x00,0xe8,0x85,0xc3,0x02,
    0x00,0x89,0xc6,0x48,0x8d,0x0d,0x5c,0x17,0x10,0x00,0xff,0x15,0x66,0x6e,0x0c,0x00,
    0x89,0xf0,0x48,0x83,0xc4,0x20,0x5e,0xc3,0x48,0x8d,0x0d,0x57,0x17,0x10,0x00,0xe8,
    0x22,0xf9,0xff,0xff,0xc6,0x05,0x43,0x17,0x10,0x00,0x01,0xeb,0xc8,0x48,0x8d,0x0d
};
static const unsigned char pa126_failure_code[32] = {
    0x48,0x8d,0x4c,0x24,0x24,0xc7,0x01,0x2f,0x00,0x00,0x00,0xe8,0xdc,0xc4,0xf3,0xff,
    0xcc,0xcc,0x0f,0x0b,0xcc,0xcc,0xcc,0xcc,0xcc,0xcc,0xcc,0xcc,0x48,0x83,0xec,0x28
};
static uint32_t read32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
int ios_steam_cef_pa126_image(const unsigned char *mapped, size_t size)
{
    uint32_t pe;
    if (!mapped || size < 0x166000 || size > 0x168000 || mapped[0]!='M' || mapped[1]!='Z') return 0;
    pe = read32(mapped+0x3c);
    if (pe < 64 || pe > size-84 || memcmp(mapped+pe,"PE\0\0",4) ||
        mapped[pe+4]!=0x64 || mapped[pe+5]!=0x86 || read32(mapped+pe+8)!=0x66956fee ||
        read32(mapped+pe+80)!=0x166000) return 0;
    return !memcmp(mapped+0x4e0aa,pa126_allocate_code,sizeof(pa126_allocate_code)) &&
           !memcmp(mapped+0xdc0f4,pa126_failure_code,sizeof(pa126_failure_code));
}

static pthread_mutex_t pool_lock=PTHREAD_MUTEX_INITIALIZER;
static struct { uintptr_t owner;char run[37]; } qualified[32];

void ios_steam_cef_pool_image(const char *run, uintptr_t owner, const uint16_t *image, size_t chars,
                              unsigned int machine, const unsigned char *mapped, size_t size)
{
    size_t i,slot=32;
    if (!owner || !ios_steam_cef_valid_run(run) || !ios_steam_cef_win64_helper(image,chars,machine)) return;
    if (!ios_steam_cef_pa126_image(mapped,size))
    {
        ios_steam_cef_pool_forget(run,owner);
        fprintf(stderr,"[steam-cef-va] chrome_elf build not recognized; version-specific aligned placement remains disabled\n");
        return;
    }
    pthread_mutex_lock(&pool_lock);
    for (i=0;i<32;i++)
    {
        if (qualified[i].owner==owner && !strcmp(qualified[i].run,run)) {slot=i;break;}
        if (!qualified[i].owner && slot==32) slot=i;
    }
    if (slot<32) {qualified[slot].owner=owner;memcpy(qualified[slot].run,run,37);}
    pthread_mutex_unlock(&pool_lock);
    if (slot<32) fprintf(stderr,"[steam-cef-va] verified Chromium 126 allocator; full-size aligned pool placement enabled for this helper\n");
}
void ios_steam_cef_pool_forget(const char *run, uintptr_t owner)
{
    size_t i;
    if (!owner || !ios_steam_cef_valid_run(run)) return;
    pthread_mutex_lock(&pool_lock);
    for (i=0;i<32;i++)
        if (qualified[i].owner==owner && !strcmp(qualified[i].run,run)) qualified[i].owner=0;
    pthread_mutex_unlock(&pool_lock);
}

int ios_steam_cef_pool_reserve(const char *run, uintptr_t owner, const uint16_t *image, size_t chars,
                              unsigned int machine, uint64_t hint, uint64_t size, unsigned int type,
                              unsigned int protect, uint64_t host_limit, ios_steam_cef_fixed_reserve reserve,
                              void *context, uint64_t *placed)
{
    const uint64_t pool=0x400000000ull,guard=0x10000ull;
    uint64_t candidate;
    size_t i;
    int known=0;
    unsigned int status;
    if (!placed || !reserve || !owner || !ios_steam_cef_valid_run(run) ||
        !ios_steam_cef_win64_helper(image,chars,machine) || type!=0x2000 || protect!=1 ||
        !hint || !host_limit || hint<host_limit) return 0;
    /* PA126's random VirtualAlloc addresses are hints to its own retry loop.
     * Fixed requests within the device map keep normal Windows semantics.
     * Regular pool goes above the guarded pool, leaving the 64 KiB forbidden
     * zone below the lower pool instead of inside the regular pool. */
    if (size==pool && !(hint&(pool-1))) candidate=0x7800000000ull;
    else if (size==pool+guard && (hint&(pool-1))==pool-guard) candidate=0x73ffff0000ull;
    else return 0;
    if (candidate>=host_limit || size>host_limit-candidate) return 0;
    pthread_mutex_lock(&pool_lock);
    for (i=0;i<32;i++)
        if (qualified[i].owner==owner && !strcmp(qualified[i].run,run)) {known=1;break;}
    pthread_mutex_unlock(&pool_lock);
    if (!known) return 0;
    status=reserve(context,candidate,size);
    if (status)
    {
        fprintf(stderr,"[steam-cef-va] full-size pool candidate unavailable (status=0x%x); ordinary allocation failure path preserved\n",status);
        return 0;
    }
    *placed=candidate;
    fprintf(stderr,"[steam-cef-va] real %llu MB %s pool reserved at 0x%llx; oversized alignment probe avoided\n",
        (unsigned long long)(size>>20),size==pool?"regular":"guarded",(unsigned long long)candidate);
    return 1;
}
