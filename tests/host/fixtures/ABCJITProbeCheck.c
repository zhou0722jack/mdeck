#include <mach/mach.h>
#include <mach/vm_map.h>
#include <signal.h>
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "JITAllocator.h"

#define PAGE 0x4000
enum { OK, NO_FLAGS, RX_DENIED, RW_DENIED, EXEC_FAULT, WRONG_RESULT, RESTORE_DENIED, FOREIGN_FAULT, STORE_FAULT };
static int scenario, restoring, real_execution, foreign_faults, one_shot, store_faulted;
static unsigned executions[3];
static JITEntryProbeRegion fixture_regions[3];
static unsigned char before[3][PAGE];

bool jit_cs_status(uint32_t *flags) { *flags=scenario==NO_FLAGS?0:0x10000000u;return true; }
static kern_return_t fixture_region(vm_map_t task, vm_address_t *at, vm_size_t *size, vm_region_flavor_t flavor,
    vm_region_info_t info, mach_msg_type_number_t *count, mach_port_t *object)
{
    vm_address_t wanted=*at;
    kern_return_t kr=vm_region_64(task,at,size,flavor,info,count,object);
    if(kr==KERN_SUCCESS) {
        vm_region_basic_info_64_t out=(vm_region_basic_info_64_t)info;
        for(unsigned i=0;i<3;i++) {
            if(wanted>=fixture_regions[i].rx && wanted-fixture_regions[i].rx<PAGE) {
                if(!real_execution) out->protection|=VM_PROT_EXECUTE;
                if(scenario==RX_DENIED && i==0) out->protection&=~VM_PROT_EXECUTE;
            }
            if(wanted>=fixture_regions[i].rw && wanted-fixture_regions[i].rw<PAGE && i==0 &&
                (scenario==RW_DENIED || (scenario==RESTORE_DENIED && restoring)))
                out->protection&=~VM_PROT_WRITE;
        }
    }
    return kr;
}
static int64_t fixture_execute(void *address);
static void *fixture_copy(void *destination, const void *source, size_t size);
#define vm_region_64 fixture_region
#define memcpy fixture_copy
#define MADEIRA_ENTRY_PROBE_EXECUTE fixture_execute
#include "PROBE_SOURCE"
#undef vm_region_64
#undef memcpy

static void *fixture_copy(void *destination, const void *source, size_t size)
{
    if(scenario==STORE_FAULT && !store_faulted && probe_dirty_mask &&
        (uintptr_t)destination==fixture_regions[0].rw+PAGE-8 && size==8) {
        store_faulted=1;memcpy(destination,source,4); /* Simulate a partial store. */
        ucontext_t context={0};__typeof__(*context.uc_mcontext) machine={0};context.uc_mcontext=&machine;
        machine.__ss.__pc=0x1234;
        siginfo_t info={0};info.si_addr=(char *)destination+4;
        probe_fault(SIGBUS,&info,&context);
        assert(!"borrowed-byte store fault must be caught");
    }
    return memcpy(destination,source,size);
}

static int64_t fixture_execute(void *address)
{
    unsigned index=3;
    for(unsigned i=0;i<3;i++) if((uintptr_t)address==fixture_regions[i].rx+PAGE-8) index=i;
    assert(index<3);executions[index]++;
    const uint32_t code[]={0xD2800540u,0xD65F03C0u};assert(!memcmp(address,code,8));
    if(one_shot) probe_previous[0].sa_flags|=SA_RESETHAND;
    if((scenario==EXEC_FAULT && index==1) || (scenario==FOREIGN_FAULT && index==0)) {
        ucontext_t context={0};__typeof__(*context.uc_mcontext) machine={0};context.uc_mcontext=&machine;
        machine.__ss.__pc=scenario==EXEC_FAULT?(uintptr_t)address:0x1234;
        probe_fault(SIGBUS,NULL,&context);
        assert(scenario==FOREIGN_FAULT);
    }
    if(scenario==RESTORE_DENIED && index==0) restoring=1;
    if(scenario==WRONG_RESULT && index==0) return 99;
    return real_execution?((int64_t (*)(void))address)():42;
}

static void previous_fault(int sig) { assert(sig==SIGBUS);foreign_faults++; }
static void reset_probe(void)
{
    memset(probe_regions,0,sizeof(probe_regions));memset(&probe_report,0,sizeof(probe_report));
    memset(probe_original,0,sizeof(probe_original));memset(executions,0,sizeof(executions));
    probe_dirty_mask=0;probe_bound=probe_sealed=probe_cleanup_failed=0;probe_pc=probe_access_lo=0;
    scenario=OK;restoring=0;one_shot=store_faulted=0;
    for(unsigned i=0;i<3;i++) memcpy((void *)fixture_regions[i].rw,before[i],PAGE);
}
static void unchanged(void)
{
    for(unsigned i=0;i<3;i++) {
        assert(!memcmp((void *)fixture_regions[i].rw,before[i],PAGE));
        assert(!memcmp((void *)fixture_regions[i].rx,before[i],PAGE));
    }
}
static void bind_all(void) { assert(jit_entry_probe_bind(fixture_regions,3)==0); }

int main(void)
{
    struct sigaction old={0},saved;old.sa_handler=previous_fault;sigemptyset(&old.sa_mask);
    assert(!sigaction(SIGBUS,&old,&saved));
    real_execution=1;
    for(unsigned i=0;i<3;i++) {
        vm_address_t rx=0,rw=0;vm_prot_t current=0,maximum=0;
        assert(vm_allocate(mach_task_self(),&rx,PAGE,VM_FLAGS_ANYWHERE)==KERN_SUCCESS);
        assert(vm_remap(mach_task_self(),&rw,PAGE,0,VM_FLAGS_ANYWHERE,mach_task_self(),rx,FALSE,
                        &current,&maximum,VM_INHERIT_NONE)==KERN_SUCCESS);
        assert(rx!=rw);
        assert(vm_protect(mach_task_self(),rw,PAGE,FALSE,VM_PROT_READ|VM_PROT_WRITE)==KERN_SUCCESS);
        memset(before[i],0x31+(int)i,PAGE);memcpy((void *)rw,before[i],PAGE);
        if(vm_protect(mach_task_self(),rx,PAGE,FALSE,VM_PROT_READ|VM_PROT_EXECUTE)!=KERN_SUCCESS) real_execution=0;
        fixture_regions[i]=(JITEntryProbeRegion){rx,rw,PAGE};
    }
    reset_probe();bind_all();
    for(unsigned round=0;round<1000;round++) { assert(jit_entry_probe_once()==42);unchanged(); }
    JITEntryProbeReport report={0};jit_entry_probe_copy_report(&report);
    assert(report.available_mask==7 && report.tested_mask==7 && report.passed_mask==7);
    assert(report.a==42 && report.b==42 && report.c==42);
    assert(executions[0]==1000 && executions[1]==1000 && executions[2]==1000);
    printf("PASS: 1000 rounds execute A/B/C, return 42 and restore every original byte (%s)\n",
           real_execution?"real host ARM64 execution":"injected host execution; host execute permission unavailable");
    assert(jit_entry_probe_release()==0 && jit_entry_probe_release()==0);
    assert(jit_entry_probe_once()==-6 && jit_entry_probe_bind(fixture_regions,3)==0 && jit_entry_probe_once()==-6);
    unchanged();
    puts("PASS: handoff seals execution permanently, preserves pool mappings and cannot be reopened by a late bind");

    reset_probe();JITEntryProbeRegion partial[3]={fixture_regions[0],{0},fixture_regions[2]};
    assert(jit_entry_probe_bind(partial,3)==0 && jit_entry_probe_once()==1);
    jit_entry_probe_copy_report(&report);
    assert(report.available_mask==5 && report.tested_mask==5 && report.passed_mask==5 && report.b==0);
    assert(executions[0]==1 && executions[1]==0 && executions[2]==1);unchanged();
    assert(jit_entry_probe_release()==0);
    puts("PASS: missing B stays unallocated/untested, receives no fabricated success, and does not block an intact-pool handoff");

    const int64_t expected[]={42,-2,-1,-1,-3,-1,-4,42,-3};
    for(scenario=NO_FLAGS;scenario<=STORE_FAULT;) {
        int selected=scenario;reset_probe();scenario=selected;bind_all();
        assert(jit_entry_probe_once()==expected[scenario]);jit_entry_probe_copy_report(&report);
        if(scenario==NO_FLAGS) assert(report.tested_mask==0 && executions[0]==0);
        if(scenario==EXEC_FAULT) assert(report.a==42 && report.b==-3 && report.c==42 && report.passed_mask==5);
        if(scenario==STORE_FAULT) assert(report.a==-3 && report.b==42 && report.c==42 && store_faulted);
        if(scenario==WRONG_RESULT) assert(report.a==99 && report.b==42 && report.c==42);
        if(scenario==RESTORE_DENIED) {
            assert(probe_dirty_mask==1 && report.a==-4 && report.tested_mask==1);
            assert(jit_entry_probe_release()==-4 && jit_entry_probe_once()==-6);
        } else { unchanged();assert(jit_entry_probe_release()==0); }
        struct sigaction restored;assert(!sigaction(SIGBUS,NULL,&restored));assert(restored.sa_handler==previous_fault);
        scenario=selected+1;
    }
    assert(foreign_faults==1);
    puts("PASS: signing/protection/partial-store/wrong-return/execution faults preserve per-region results; failed restoration refuses handoff; foreign signal action survives");

    reset_probe();vm_address_t original_rx=fixture_regions[0].rx,unrelated_rx=0;
    assert(vm_allocate(mach_task_self(),&unrelated_rx,PAGE,VM_FLAGS_ANYWHERE)==KERN_SUCCESS);
    memcpy((void *)unrelated_rx,before[0],PAGE);
    if(real_execution) assert(vm_protect(mach_task_self(),unrelated_rx,PAGE,FALSE,VM_PROT_READ|VM_PROT_EXECUTE)==KERN_SUCCESS);
    fixture_regions[0].rx=unrelated_rx;
    bind_all();assert(jit_entry_probe_once()==-1 && executions[0]==0);unchanged();
    assert(jit_entry_probe_release()==0);
    fixture_regions[0].rx=original_rx;
    assert(vm_deallocate(mach_task_self(),unrelated_rx,PAGE)==KERN_SUCCESS);
    puts("PASS: equal original bytes in unrelated RX/RW mappings do not fake an alias; code is never executed from the wrong mapping");

    reset_probe();JITEntryProbeRegion bad[3];memcpy(bad,fixture_regions,sizeof(bad));
    bad[0].rx++;assert(jit_entry_probe_bind(bad,3)==-6 && !probe_bound);
    memcpy(bad,fixture_regions,sizeof(bad));bad[1]=bad[0];assert(jit_entry_probe_bind(bad,3)==-6);
    memcpy(bad,fixture_regions,sizeof(bad));bad[0].rx=UINTPTR_MAX-0x3fff;bad[0].size=0x8000;
    assert(jit_entry_probe_bind(bad,3)==-6);
    assert(jit_entry_probe_bind(NULL,3)==-6 && jit_entry_probe_bind(fixture_regions,2)==-6);
    bind_all();assert(!pthread_mutex_lock(&probe_lock));
    assert(jit_entry_probe_once()==-5 && jit_entry_probe_release()==-5 && jit_entry_probe_bind(fixture_regions,3)==-5);
    assert(!pthread_mutex_unlock(&probe_lock));unchanged();
    assert(jit_entry_probe_release()==0);
    reset_probe();assert(jit_entry_probe_release()==0 && jit_entry_probe_bind(fixture_regions,3)==-6);
    puts("PASS: malformed/overlapping/wrapped bindings are rejected; concurrent calls are refused; handoff before binding cannot later enable writes");

    reset_probe();one_shot=1;scenario=EXEC_FAULT;
    old.sa_flags=SA_RESETHAND;assert(!sigaction(SIGBUS,&old,NULL));
    struct sigaction configured;assert(!sigaction(SIGBUS,NULL,&configured));
    bind_all();assert(jit_entry_probe_once()==-3);unchanged();
    struct sigaction restored;assert(!sigaction(SIGBUS,NULL,&restored));
    assert(restored.sa_handler==previous_fault && restored.sa_flags==configured.sa_flags);
    assert(probe_previous[0].sa_flags&SA_RESETHAND);
    assert(jit_entry_probe_release()==0);
    assert(!sigaction(SIGBUS,&saved,NULL));
    for(unsigned i=0;i<3;i++) {
        assert(vm_deallocate(mach_task_self(),fixture_regions[i].rw,PAGE)==KERN_SUCCESS);
        assert(vm_deallocate(mach_task_self(),fixture_regions[i].rx,PAGE)==KERN_SUCCESS);
    }
    puts("PASS: one-shot signal semantics are preserved; fixture alone owns mapping allocation and teardown");
    return 0;
}
