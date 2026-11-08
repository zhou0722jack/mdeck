#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "steam_cef_guard.h"

#define X64 0x8664u
#define RESERVE 0x2000u
#define NO_MEMORY 0xc0000017u
#define BREAKPOINT 0x80000003u
static const char run_a[]="00000000-0000-4000-8000-000000000001";
static const char run_b[]="00000000-0000-4000-8000-000000000002";
static uint16_t helper[160],other[160];
static size_t helper_chars;
static unsigned notifications;
static char notified_run[37];
static size_t wide(uint16_t *out,const char *text)
{
    size_t i;for(i=0;text[i];i++)out[i]=(unsigned char)text[i];out[i]=0;return i;
}
void madeira_steam_cef_address_failure(const char *run)
{
    notifications++;memcpy(notified_run,run,sizeof(notified_run));
    /* The production callback must be outside its mutex. */
    assert(ios_steam_cef_spawn_blocked(run,helper,helper_chars,X64,0));
}
static void allocation(const char *run,uintptr_t owner,uint64_t size,unsigned type,unsigned status)
{
    ios_steam_cef_allocation_result(run,owner,helper,helper_chars,X64,size,type,status);
}
static void exited(const char *run,uintptr_t owner,unsigned status)
{
    ios_steam_cef_process_exit(run,owner,helper,helper_chars,X64,status);
}
static int blocked(const char *run)
{
    return ios_steam_cef_spawn_blocked(run,helper,helper_chars,X64,0);
}
static void *parallel_exit(void *owner)
{
    exited(run_a,(uintptr_t)owner,BREAKPOINT);return NULL;
}
int main(void)
{
    helper_chars=wide(helper,"C:\\Program Files\\Steam Client\\bin\\cef\\cef.win64\\steamwebhelper.exe");
    assert(!blocked(run_a));
    /* Real log: conflicting 16 GB hints, a successful regular reservation,
     * then failed 32 GB pools followed by chrome_elf's breakpoint. */
    allocation(run_a,1,16ull<<30,RESERVE,0xc0000018u);
    allocation(run_a,1,16ull<<30,RESERVE,0);
    exited(run_a,1,BREAKPOINT);assert(!blocked(run_a)&&!notifications);
    allocation(run_a,1,32ull<<30,RESERVE,NO_MEMORY);
    exited(run_a,2,BREAKPOINT);exited(run_a,2,0);exited(run_a,2,0xc0000005u);
    assert(!blocked(run_a)&&!notifications);
    /* A 16 GB success cannot erase the failed 32 GB probe record. */
    allocation(run_a,1,16ull<<30,RESERVE,0);
    pthread_t a,b;
    assert(!pthread_create(&a,NULL,parallel_exit,(void *)1));
    assert(!pthread_create(&b,NULL,parallel_exit,(void *)1));
    assert(!pthread_join(a,NULL)&&!pthread_join(b,NULL));
    assert(blocked(run_a)&&notifications==1&&!strcmp(notified_run,run_a));
    assert(!ios_steam_cef_spawn_blocked(run_a,helper,helper_chars,X64,1)); /* crashpad */
    assert(!ios_steam_cef_spawn_blocked(run_a,helper,helper_chars,0x14c,0));
    size_t n=wide(other,"C:\\Other\\steamwebhelper.exe");
    assert(!ios_steam_cef_spawn_blocked(run_a,other,n,X64,0));
    n=wide(other,"C:\\Program Files\\Steam Client\\steamapps\\common\\Fixture\\steamwebhelper.exe");
    assert(!ios_steam_cef_spawn_blocked(run_a,other,n,X64,0));
    n=wide(other,"C:\\Program Files (x86)\\Steam\\bin\\cef\\cef.win64\\steamwebhelper.exe");
    assert(!ios_steam_cef_spawn_blocked(run_a,other,n,X64,0));
    assert(!blocked(run_b)); /* explicit new app launch has a fresh generation */
    allocation(run_b,1,32ull<<30,RESERVE,NO_MEMORY);
    allocation(run_b,1,(32ull<<30)-65536,RESERVE,0); /* allocator fallback succeeded */
    exited(run_b,1,BREAKPOINT);assert(!blocked(run_b)&&notifications==1);
    /* Small/JIT allocations, commit failures and wrong statuses never stop CEF. */
    allocation(run_b,3,64ull<<20,RESERVE,NO_MEMORY);
    allocation(run_b,3,32ull<<30,RESERVE|0x1000u,NO_MEMORY);
    allocation(run_b,3,32ull<<30,RESERVE,0xc000000du);
    exited(run_b,3,BREAKPOINT);assert(!blocked(run_b));
    allocation(run_b,7,32ull<<30,RESERVE,NO_MEMORY);
    exited(run_b,7,0);exited(run_b,7,BREAKPOINT);
    assert(!blocked(run_b)); /* a reused PEB cannot inherit a normal exit's record */
    allocation(NULL,4,32ull<<30,RESERVE,NO_MEMORY);
    allocation("not-a-run",4,32ull<<30,RESERVE,NO_MEMORY);
    exited(run_b,4,BREAKPOINT);assert(!blocked(run_b));
    ios_steam_cef_allocation_result(run_b,5,helper,helper_chars,0x14c,32ull<<30,RESERVE,NO_MEMORY);
    exited(run_b,5,BREAKPOINT);assert(!blocked(run_b));
    n=wide(other,"\\??\\c:/PROGRAM FILES/steam client/bin/cef/cef.win64/STEAMWEBHELPER.EXE");
    ios_steam_cef_allocation_result(run_b,6,other,n,X64,32ull<<30,RESERVE,NO_MEMORY);
    ios_steam_cef_process_exit(run_b,6,other,n,X64,BREAKPOINT);
    assert(blocked(run_b)&&notifications==2);
    puts("PASS: real failed-reserve/exit sequence stops repeated Win64 browser creation; one notification outside mutex, owner/run isolation, successful fallback, crashpad/32-bit/other-path exclusions");
    return 0;
}
