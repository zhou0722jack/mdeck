#!/usr/bin/env python3
"""Test entry JIT scheduling and real native cleanup with injected debugger/Mach failures."""
import platform
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app/Madeira'
swift = (APP / 'AppEntryJIT.swift').read_text()
core = swift[swift.index('// MARK: - Entry JIT policy'):swift.index('// MARK: - Production adapter')]
content = (APP / 'ContentView.swift').read_text()
assert 'AppEntryJIT.shared.enable { result in' in content
wine = content[content.index('    private func runWineFullSequence('):]
assert wine.index('deferLaunchUntilProbeFinishes') < wine.index('StikJITHelper.allocatePool(')
root = (APP / 'DeckStartup.swift').read_text()
assert 'sceneChanged(active: entryScenePhase == .active, allowed: startup.phase == .ready)' in root
assert 'sceneChanged(active: phase == .active, allowed: startup.phase == .ready)' in root
assert 'static let interval: TimeInterval = 5' in swift and 'static let probeBytes = 16 * 1024' in swift
project = (ROOT / 'app/Madeira.xcodeproj/project.pbxproj').read_text()
assert project.count('/* AppEntryJIT.swift in Sources */') == 2
assert project.count('/* AppEntryJITProbe.c in Sources */') == 2

harness = r'''
import SwiftUI
func L(_ key: String) -> String { key }
func LF(_ key: String, _ args: CVarArg...) -> String { String(format:key,arguments:args) }
@MainActor final class LogStore { static let shared=LogStore(); func log(_ value:String) {} }
extension AppEntryJIT.Services { static var live: Self { fatalError("live service is never used") } }
@MainActor final class Fake {
    var ready=false, attached=false, enableCalls=0, probes=0, cancels=0, releases=0
    var intervals:[TimeInterval]=[]
    var enables:[(Result<Void,Error>)->Void]=[]
    var executions:[(Int64)->Void]=[]
    var cleanups:[(Int64)->Void]=[]
    var tick:(()->Void)?
    func services() -> AppEntryJIT.Services {
        .init(enable:{ self.enableCalls+=1; self.enables.append($0) },
              ready:{ self.ready }, attached:{ self.attached },
              probe:{ self.probes+=1; self.executions.append($0) },
              release:{ self.releases+=1; self.cleanups.append($0) },
              schedule:{ interval,tick in self.intervals.append(interval); self.tick=tick
                  return { self.cancels+=1; self.tick=nil }
              })
    }
    func enabled() { ready=true; attached=true; let f=enables.removeFirst(); f(.success(())) }
    func completed(_ result:Int64) { let f=executions.removeFirst(); f(result) }
    func released(_ result:Int64=0) { let f=cleanups.removeFirst(); f(result) }
}
@main struct Check {
    @MainActor static func main() {
        var fake=Fake()
        var model=AppEntryJIT(services:fake.services())
        model.sceneChanged(active:true,allowed:false)
        precondition(fake.enableCalls==0)
        model.sceneChanged(active:true,allowed:true)
        model.sceneChanged(active:true,allowed:true)
        var joined=0
        model.enable { _ in joined+=1 }
        precondition(fake.enableCalls==1 && fake.probes==0)
        fake.enabled()
        precondition(joined==1 && fake.intervals==[5] && fake.probes==1)
        model.tick(); model.tick()
        precondition(fake.probes==1)
        fake.completed(42)
        precondition(model.successfulProbes==1)
        precondition(model.lastProbeResult==42 && model.lastProbeFinishedAt != nil)
        precondition(model.probeIsHealthy(at:model.lastProbeFinishedAt!))
        precondition(!model.probeIsHealthy(at:model.lastProbeFinishedAt!.addingTimeInterval(11)))
        precondition(abs(AppEntryJIT.cycleProgress(at:Date(timeIntervalSince1970:2.5),since:Date(timeIntervalSince1970:0)) - 0.5)<0.001)
        precondition(AppEntryJIT.cycleProgress(at:Date(timeIntervalSince1970:5),since:Date(timeIntervalSince1970:0))==0)
        fake.tick?()
        precondition(fake.probes==2)
        model.sceneChanged(active:false,allowed:true)
        precondition(fake.tick==nil)
        fake.completed(42)
        model.tick()
        precondition(fake.probes==2 && model.state == .paused)
        model.sceneChanged(active:true,allowed:true)
        precondition(fake.probes==3 && fake.enableCalls==1)
        fake.completed(42)
        fake.attached=false; fake.tick?()
        precondition(fake.probes==3 && model.state == .waiting)
        fake.attached=true; fake.tick?()
        precondition(fake.probes==4)
        print("PASS: entry after choice, one shared JIT attachment, immediate/5-second probe, no overlap and background pause")

        var starts=0, failures=0
        let staleTimer=fake.tick
        precondition(model.deferLaunchUntilProbeFinishes({ starts+=1 },failed:{_ in failures+=1}))
        precondition(starts==0 && fake.tick==nil)
        staleTimer?(); model.sceneChanged(active:true,allowed:true)
        precondition(fake.probes==4)
        fake.completed(42)
        precondition(starts==0 && fake.releases==1)
        fake.released()
        precondition(starts==1 && failures==0 && model.state == .stopped)
        precondition(!model.deferLaunchUntilProbeFinishes({starts+=1},failed:{_ in failures+=1}))
        model.tick(); staleTimer?()
        precondition(fake.probes==4)
        print("PASS: launch stops timer, drains the in-flight native cleanup once and never resumes probes")

        fake=Fake(); model=AppEntryJIT(services:fake.services())
        model.sceneChanged(active:true,allowed:true)
        precondition(model.deferLaunchUntilProbeFinishes({ starts+=1 },failed:{_ in failures+=1}))
        fake.released()
        fake.enabled()
        precondition(fake.probes==0 && fake.intervals.isEmpty && model.state == .stopped)
        print("PASS: a late initial attachment cannot restart the loop after a launch handoff")

        fake=Fake(); model=AppEntryJIT(services:fake.services())
        model.sceneChanged(active:true,allowed:true); fake.enabled()
        fake.completed(-1)
        precondition(model.lastProbeResult == -1 && !model.probeIsHealthy(at:.now))
        precondition(fake.tick==nil && model.state == .failed)
        model.sceneChanged(active:false,allowed:true); model.sceneChanged(active:true,allowed:true)
        precondition(fake.probes==1 && model.state == .failed)
        model.enable { _ in }
        fake.enabled()
        precondition(fake.probes==2)
        precondition(model.deferLaunchUntilProbeFinishes({ starts+=1 },failed:{_ in failures+=1}))
        let before=starts
        fake.completed(-4)
        fake.released(-4)
        precondition(starts==before && failures==1 && model.state == .failed)
        var refused=false
        model.enable { result in if case .failure = result { refused=true } }
        precondition(refused && fake.enableCalls==2)
        print("PASS: failed native probes stop retries; failed unmapping refuses launch and requests reopening")

        fake=Fake(); model=AppEntryJIT(services:fake.services())
        model.sceneChanged(active:true,allowed:true); fake.enabled()
        for _ in 0..<1000 { fake.completed(42); fake.tick?() }
        precondition(fake.probes==1001 && fake.enableCalls==1 && fake.releases==0)
        let launchCount=starts
        precondition(model.deferLaunchUntilProbeFinishes({starts+=1},failed:{_ in failures+=1}))
        fake.completed(42)
        precondition(starts==launchCount && fake.releases==1)
        model.tick(); precondition(fake.probes==1001)
        fake.released()
        precondition(starts==launchCount+1)
        print("PASS: 1000 scheduled rounds do not reattach or release early; startup waits for scratch release")

        fake=Fake(); model=AppEntryJIT(services:fake.services())
        model.sceneChanged(active:true,allowed:true); fake.enabled(); fake.completed(42)
        let beforeReleaseFailure=starts
        precondition(model.deferLaunchUntilProbeFinishes({starts+=1},failed:{_ in failures+=1}))
        precondition(model.deferLaunchUntilProbeFinishes({starts+=1},failed:{_ in failures+=1}))
        precondition(fake.releases==1)
        fake.released(-4)
        precondition(starts==beforeReleaseFailure && model.state == .failed)
        model.tick(); precondition(fake.probes==1)
        print("PASS: duplicate handoffs share one release; failure blocks startup after a successful last probe")
    }
}
'''

c_harness = r'''
#include <mach/mach.h>
#include <mach/vm_map.h>
#include <sys/sysctl.h>
#include <signal.h>
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "JITAllocator.h"
enum { OK,NO_FLAGS,NO_DEBUGGER,ALLOC_FAIL,REMAP_FAIL,PROTECT_FAIL,RX_DENIED,EXEC_FAULT,
       FOREIGN_FAULT,RW_FREE_FAIL,RX_FREE_FAIL };
static int scenario,allocs,frees,old_faults,force_one_shot;
static void *owned_rx;
static vm_address_t owned_rw;
static int fixture_sysctl(int *m,u_int n,void *out,size_t *size,void *v,size_t len) {
    (void)m;(void)n;(void)size;(void)v;(void)len;
    memset(out,0,sizeof(struct kinfo_proc));
    if(scenario!=NO_DEBUGGER) ((struct kinfo_proc *)out)->kp_proc.p_flag=P_TRACED;
    return 0;
}
bool jit_cs_status(uint32_t *flags) { *flags=scenario==NO_FLAGS?0:0x10000000u;return true; }
void jit_arm_trap_fallback(void) {}
void *jit26_prepare_region(void *address,size_t size) {
    assert(!address && size==16384);
    if(scenario==ALLOC_FAIL) return NULL;
    vm_address_t at=0;assert(vm_allocate(mach_task_self(),&at,size,VM_FLAGS_ANYWHERE)==KERN_SUCCESS);
    owned_rx=(void *)at;allocs++;return owned_rx;
}
static kern_return_t fixture_remap(vm_map_t target,vm_address_t *at,vm_size_t size,vm_address_t mask,
    int flags,vm_map_t source,vm_address_t from,boolean_t copy,vm_prot_t *current,vm_prot_t *max,vm_inherit_t inherit) {
    if(scenario==REMAP_FAIL) return KERN_NO_SPACE;
    kern_return_t kr=vm_remap(target,at,size,mask,flags,source,from,copy,current,max,inherit);
    if(kr==KERN_SUCCESS) {owned_rw=*at;allocs++;} return kr;
}
static kern_return_t fixture_protect(vm_map_t task,vm_address_t at,vm_size_t size,boolean_t max,vm_prot_t prot) {
    if(scenario==PROTECT_FAIL) return KERN_PROTECTION_FAILURE;
    return vm_protect(task,at,size,max,prot);
}
static kern_return_t fixture_region(vm_map_t task,vm_address_t *at,vm_size_t *size,vm_region_flavor_t flavor,
    vm_region_info_t info,mach_msg_type_number_t *count,mach_port_t *object) {
    int rx=*at==(vm_address_t)owned_rx;
    kern_return_t kr=vm_region_64(task,at,size,flavor,info,count,object);
    if(kr==KERN_SUCCESS && rx && scenario!=RX_DENIED)
        ((vm_region_basic_info_64_t)info)->protection |= VM_PROT_EXECUTE;
    return kr;
}
static kern_return_t fixture_free(vm_map_t task,vm_address_t at,vm_size_t size) {
    assert(size==16384);
    if(at==owned_rw) {const unsigned char *p=(void *)at;for(unsigned i=0;i<size;i++) assert(p[i]==0);}
    assert(vm_deallocate(task,at,size)==KERN_SUCCESS);frees++;
    if((scenario==RW_FREE_FAIL && at==owned_rw)||(scenario==RX_FREE_FAIL && at==(vm_address_t)owned_rx)) return KERN_FAILURE;
    return KERN_SUCCESS;
}
static int64_t fixture_execute(void *address);
#define sysctl fixture_sysctl
#define vm_remap fixture_remap
#define vm_protect fixture_protect
#define vm_region_64 fixture_region
#define vm_deallocate fixture_free
#define MADEIRA_ENTRY_PROBE_EXECUTE fixture_execute
#include "PROBE_SOURCE"
static void previous_fault(int sig) {(void)sig;old_faults++;}
static int64_t fixture_execute(void *address) {
    const uint32_t expected[]={0xD2800540u,0xD65F03C0u};assert(!memcmp(address,expected,8));
    /* Darwin may omit SA_RESETHAND when reporting SIGBUS. Inject the saved
     * action bit to exercise forwarding semantics independently of that OS. */
    if(force_one_shot) probe_previous[0].sa_flags |= SA_RESETHAND;
    if(scenario==EXEC_FAULT || scenario==FOREIGN_FAULT) {
        ucontext_t context={0};__typeof__(*context.uc_mcontext) machine={0};
        context.uc_mcontext=&machine;
        machine.__ss.__pc=scenario==EXEC_FAULT?(uintptr_t)address:0x1234;
        probe_fault(SIGBUS,NULL,&context);
        assert(scenario==FOREIGN_FAULT);
    }
    return 42;
}
int main(void) {
    struct sigaction old={0},saved;old.sa_handler=previous_fault;sigemptyset(&old.sa_mask);
    assert(!sigaction(SIGBUS,&old,&saved));
    const int64_t expected[]={42,-2,-2,-1,-1,-1,-1,-3,42,-4,-4};
    for(scenario=OK;scenario<=RX_FREE_FAIL;scenario++) {
        allocs=frees=0;owned_rx=NULL;owned_rw=0;
        scratch_cleanup_failed=0;
        int64_t result=jit_entry_probe_once();
        if(scenario==RW_FREE_FAIL || scenario==RX_FREE_FAIL) {
            assert(result==42);assert(jit_entry_probe_release()==-4);
            assert(jit_entry_probe_once()==-4);
        } else {
            assert(result==expected[scenario]);
            assert(jit_entry_probe_release()==0);
        }
        assert(allocs==frees);
        struct sigaction restored;assert(!sigaction(SIGBUS,NULL,&restored));assert(restored.sa_handler==previous_fault);
    }
    assert(old_faults==1);
    scratch_cleanup_failed=0;scenario=OK;allocs=frees=0;owned_rx=NULL;owned_rw=0;
    for(unsigned round=0;round<1000;round++) {
        assert(jit_entry_probe_once()==42 && allocs==2 && frees==0);
        const unsigned char *p=(void *)owned_rw;
        for(unsigned i=0;i<16384;i++) assert(p[i]==0);
    }
    assert(jit_entry_probe_release()==0 && allocs==frees);
    scenario=OK;allocs=frees=0;owned_rx=NULL;owned_rw=0;
    assert(jit_entry_probe_once()==42 && allocs==2);
    scenario=NO_DEBUGGER;
    assert(jit_entry_probe_once()==-2 && allocs==2 && frees==0);
    scenario=OK;
    assert(jit_entry_probe_once()==42 && allocs==2 && frees==0);
    assert(jit_entry_probe_release()==0 && frees==2);
    old.sa_flags=SA_RESETHAND;assert(!sigaction(SIGBUS,&old,NULL));
    struct sigaction configured;assert(!sigaction(SIGBUS,NULL,&configured));
    force_one_shot=1;
    scenario=EXEC_FAULT;allocs=frees=0;owned_rx=NULL;owned_rw=0;
    assert(jit_entry_probe_once()==-3 && allocs==frees);
    struct sigaction restored;assert(!sigaction(SIGBUS,NULL,&restored));
    assert(restored.sa_handler==previous_fault && restored.sa_flags==configured.sa_flags);
    assert(probe_previous[0].sa_flags & SA_RESETHAND);
    scenario=FOREIGN_FAULT;allocs=frees=0;owned_rx=NULL;owned_rw=0;
    assert(jit_entry_probe_once()==42);
    assert(jit_entry_probe_release()==0 && allocs==frees);
    assert(!sigaction(SIGBUS,NULL,&restored));assert(restored.sa_handler==SIG_DFL && old_faults==2);
    assert(!pthread_mutex_lock(&probe_lock));assert(jit_entry_probe_once()==-5);pthread_mutex_unlock(&probe_lock);
    assert(!sigaction(SIGBUS,&saved,NULL));
    puts("PASS: 1000 rounds reuse exactly one debugger allocation, wipe code each round and release both aliases at handoff; failure/signal paths verified");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='mdeck-entry-jit-') as directory:
    tmp=Path(directory)
    production=tmp/'Entry.swift';production.write_text('import SwiftUI\n'+core)
    fixture=tmp/'Check.swift';fixture.write_text(harness)
    binary=tmp/'check'
    subprocess.run(['xcrun','swiftc','-parse-as-library',str(production),str(fixture),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
    probe=APP/'AppEntryJITProbe.c'
    subprocess.run(['xcrun','--sdk','iphoneos','clang','-target','arm64-apple-ios18.0','-fsyntax-only',
                    '-Wall','-Wextra','-Werror',str(probe)],check=True)
    if platform.machine()=='arm64':
        fixture=tmp/'Probe.c';fixture.write_text(c_harness.replace('PROBE_SOURCE',str(probe)))
        binary=tmp/'probe'
        for optimization in ['-O0','-O2']:
            subprocess.run(['xcrun','clang',optimization,'-std=gnu11','-Wall','-Wextra','-Werror','-I',str(APP),
                            str(fixture),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
print('Host component tests with fake attachment/execution; no real iOS JIT or Steam acceptance claimed.')
