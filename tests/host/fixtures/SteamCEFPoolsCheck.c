#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include "steam_cef_guard.h"
#include "steam_cef_pools.h"

static const char run[]="00000000-0000-4000-8000-000000000011";
static const char later[]="00000000-0000-4000-8000-000000000012";
static uint16_t helper[160];
static size_t chars;
static const uint64_t pool=0x400000000ull,guard=0x10000ull;
void madeira_steam_cef_address_failure(const char *run_id)
{
    (void)run_id;assert(!"pool placement test must not report a process exit");
}
void madeira_steam_initial_window_failure(const char *run_id)
{
    (void)run_id;assert(!"pool placement test must not report a Steam UI exit");
}
struct span {uint64_t base,size;};
struct map {struct span ranges[8];unsigned n,calls;int fail;};
static unsigned fixed_model(void *context,uint64_t base,uint64_t size)
{
    struct map *m=context;
    m->calls++;
    if (m->fail) return 0xc0000017u;
    for (unsigned i=0;i<m->n;i++)
        if(base<m->ranges[i].base+m->ranges[i].size&&m->ranges[i].base<base+size)return 0xc0000018u;
    assert(m->n<8);m->ranges[m->n++]=(struct span){base,size};return 0;
}
static int reserve(struct map *m,uintptr_t owner,uint64_t hint,uint64_t size,uint64_t *out)
{
    return ios_steam_cef_pool_reserve(run,owner,helper,chars,0x8664,hint,size,0x2000,1,
        0x8000000000ull,fixed_model,m,out);
}
struct real_map {struct span ranges[2];unsigned n;};
static unsigned fixed_real(void *context,uint64_t base,uint64_t size)
{
    struct real_map *m=context;
    mach_vm_address_t address=base;
    kern_return_t kr=mach_vm_map(mach_task_self(),&address,size,0,VM_FLAGS_FIXED,
        MEMORY_OBJECT_NULL,0,0,VM_PROT_NONE,VM_PROT_READ|VM_PROT_WRITE,VM_INHERIT_NONE);
    if(kr!=KERN_SUCCESS)return 0xc0000017u;
    assert(address==base&&m->n<2);
    m->ranges[m->n++]=(struct span){base,size};return 0;
}
int main(int argc,char **argv)
{
    assert(argc==2);
    FILE *file=fopen(argv[1],"rb");assert(file);
    unsigned char *image=calloc(1,0x168000);assert(image);
    assert(fread(image,1,0x166000,file)==0x166000);fclose(file);
    chars=strlen("C:\\Program Files\\Steam Client\\bin\\cef\\cef.win64\\steamwebhelper.exe");
    const char *name="C:\\Program Files\\Steam Client\\bin\\cef\\cef.win64\\steamwebhelper.exe";
    for(size_t i=0;i<chars;i++)helper[i]=(unsigned char)name[i];
    assert(ios_steam_cef_pa126_image(image,0x166000));
    assert(ios_steam_cef_pa126_image(image,0x168000));
    assert(!ios_steam_cef_pa126_image(image,0x165000));
    unsigned pe=(unsigned)image[0x3c]|(unsigned)image[0x3d]<<8|(unsigned)image[0x3e]<<16|(unsigned)image[0x3f]<<24;
    image[pe+4]^=1;assert(!ios_steam_cef_pa126_image(image,0x166000));image[pe+4]^=1;
    image[pe+8]^=1;assert(!ios_steam_cef_pa126_image(image,0x166000));image[pe+8]^=1;
    image[pe+80]^=1;assert(!ios_steam_cef_pa126_image(image,0x166000));image[pe+80]^=1;
    image[0x4e0aa]^=1;assert(!ios_steam_cef_pa126_image(image,0x166000));image[0x4e0aa]^=1;
    image[0xdc104]^=1;assert(!ios_steam_cef_pa126_image(image,0x166000));image[0xdc104]^=1;
    struct map m={.ranges={{0x7000000000ull,0x3ffff0000ull},{0x7c00000000ull,0x400000000ull}},.n=2};
    uint64_t placed=0xfeed;
    assert(!reserve(&m,1,0x135400000000ull,pool,&placed)&&!m.calls&&placed==0xfeed);
    ios_steam_cef_pool_image(run,1,helper,chars,0x8664,image,0x166000);
    image[0x4e0aa]^=1;
    ios_steam_cef_pool_image(run,1,helper,chars,0x8664,image,0x166000);
    assert(!reserve(&m,1,0x135400000000ull,pool,&placed)&&!m.calls);
    image[0x4e0aa]^=1;
    ios_steam_cef_pool_image(run,1,helper,chars,0x8664,image,0x166000);
    /* Build 26's recorded fallback: 32 GB-64 KiB probe, free, then a 16 GB
     * pool at 0x7400000000. Its remaining hole is too small for a 32 GB probe. */
    struct map old=m;
    assert(!fixed_model(&old,0x73ffff0000ull,2*pool-guard));old.n--;
    assert(!fixed_model(&old,0x7400000000ull,pool));
    assert(fixed_model(&old,0x73ffff0000ull,2*pool));
    assert(fixed_model(&old,0x7800000000ull,2*pool));
    /* Same real initial holes: the new branch gives every byte requested. */
    assert(reserve(&m,1,0x135400000000ull,pool,&placed)&&placed==0x7800000000ull);
    assert(m.ranges[2].size==pool&&!(placed&(pool-1)));
    assert(reserve(&m,1,0x1933ffff0000ull,pool+guard,&placed)&&placed==0x73ffff0000ull);
    assert(m.ranges[3].size==pool+guard&&!((placed+guard)&(pool-1)));
    assert(m.ranges[3].base+m.ranges[3].size==m.ranges[2].base);
    assert(m.ranges[2].base+m.ranges[2].size==m.ranges[1].base);
    assert(m.ranges[0].base+m.ranges[0].size==m.ranges[3].base);
    puts("PASS: recorded old placement cannot fit the overreservation; full-size regular and guarded pools now fit as disjoint native ranges, preserving 16 GB alignment and the 64 KiB forbidden zone");
    unsigned calls=m.calls;
    assert(!reserve(&m,2,0x135400000000ull,pool,&placed)&&m.calls==calls);
    assert(!reserve(&m,1,0x7800000000ull,pool,&placed)&&m.calls==calls); /* real fixed requests */
    assert(!reserve(&m,1,0x135400000001ull,pool,&placed)&&m.calls==calls);
    assert(!reserve(&m,1,0x135400000000ull,2*pool,&placed)&&m.calls==calls);
    assert(!ios_steam_cef_pool_reserve(run,1,helper,chars,0x8664,0x135400000000ull,pool,0x2000,1,
        0xfc0000000ull,fixed_model,&m,&placed)&&m.calls==calls); /* smaller task map */
    assert(!ios_steam_cef_pool_reserve(later,1,helper,chars,0x8664,0x135400000000ull,pool,0x2000,1,
        0x8000000000ull,fixed_model,&m,&placed)&&m.calls==calls);
    assert(!ios_steam_cef_pool_reserve(run,1,helper,chars,0x14c,0x135400000000ull,pool,0x2000,1,
        0x8000000000ull,fixed_model,&m,&placed)&&m.calls==calls);
    assert(!ios_steam_cef_pool_reserve(run,1,helper,chars,0x8664,0x135400000000ull,pool,0x3000,1,
        0x8000000000ull,fixed_model,&m,&placed)&&m.calls==calls);
    assert(!ios_steam_cef_pool_reserve(run,1,helper,chars,0x8664,0x135400000000ull,pool,0x2000,4,
        0x8000000000ull,fixed_model,&m,&placed)&&m.calls==calls);
    m.fail=1;placed=0xbeef;
    assert(!reserve(&m,1,0x135400000000ull,pool,&placed)&&placed==0xbeef);
    ios_steam_cef_pool_forget(run,1);calls=m.calls;
    assert(!reserve(&m,1,0x135400000000ull,pool,&placed)&&m.calls==calls);
    puts("PASS: unknown image/owner/run, 32-bit, commit/protection/shape changes and in-range fixed addresses keep normal behavior; backend failures never become success and dead identities are dropped");
    /* Native kernel corroboration: no MAP_FIXED overwrite, no fake size.
     * Reserve all 32 GB+64 KiB as PROT_NONE and touch only four own pages. */
    ios_steam_cef_pool_image(run,3,helper,chars,0x8664,image,0x166000);
    struct real_map real={0};
    int regular=ios_steam_cef_pool_reserve(run,3,helper,chars,0x8664,0x135400000000ull,pool,0x2000,1,
        0x8000000000ull,fixed_real,&real,&placed);
    int brp=regular&&ios_steam_cef_pool_reserve(run,3,helper,chars,0x8664,0x1933ffff0000ull,pool+guard,0x2000,1,
        0x8000000000ull,fixed_real,&real,&placed);
    if(regular&&brp)
    {
        mach_vm_size_t page=vm_page_size;
        uint64_t pages[]={real.ranges[0].base,real.ranges[0].base+pool-page,
            real.ranges[1].base+guard,real.ranges[1].base+pool+guard-page};
        for(unsigned i=0;i<4;i++)
        {
            assert(mach_vm_protect(mach_task_self(),pages[i],page,0,VM_PROT_READ|VM_PROT_WRITE)==KERN_SUCCESS);
            *(volatile uint64_t *)(uintptr_t)pages[i]=0x1234567800000000ull+i;
        }
        for(unsigned i=0;i<4;i++)assert(*(volatile uint64_t *)(uintptr_t)pages[i]==0x1234567800000000ull+i);
        puts("PASS: host Mach kernel reserved the full 32 GB+64 KiB without replacement; first and last pages of both real pools are independently writable");
    }
    else puts("SKIP: host map cannot corroborate these exact iOS-band addresses; modeled placement checks still ran");
    for(unsigned i=0;i<real.n;i++)assert(mach_vm_deallocate(mach_task_self(),real.ranges[i].base,real.ranges[i].size)==KERN_SUCCESS);
    free(image);return 0;
}
