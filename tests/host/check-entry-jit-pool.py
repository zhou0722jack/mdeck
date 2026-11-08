#!/usr/bin/env python3
"""Compile production early-hold, pool-cache and settings code with injected VM/debugger adapters.

No iOS JIT request, Wine execution, signing or IPA build. Exact iPad address
availability and the real debugger handoff remain device acceptance gates.
"""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
native = (app / 'JITAllocator.c').read_text()
swift = (app / 'StikJITHelper.swift').read_text()


def function(source, signature, closing='\n    }'):
    start = source.index(signature)
    return source[start:source.index(closing, start) + len(closing)] + '\n'


helpers = native[native.index('/* Entry A/B/C holds.'):native.index('/* End entry A/B/C hold helpers. */')]
assert 'VM_FLAGS_OVERWRITE' not in helpers
constructor = native[native.index('__attribute__((constructor(101), used)) static void madeira_early_va_claim(void)'):]
constructor = constructor[:constructor.index('/* ml1249:')]
assert 'madeira_early_region_claim(MADEIRA_EARLY_REGION_B,' in constructor
assert 'madeira_early_pool_base + madeira_early_pool_size, 0x180000000ul, 0)' in constructor
assert 'madeira_early_region_claim(MADEIRA_EARLY_REGION_C,' in constructor
assert 'madeira_cfg_int("pool-low-margin", 128)' in constructor
assert 'margin_mb > 4096' in constructor and 'margin_mb < 0' in constructor
fresh = swift[swift.index('private static func allocateFreshPool('):swift.index('private static func poolRunSize(')]
assert fresh.index('releaseEarlyRegion(MADEIRA_EARLY_REGION_B, reason: "A/B allocation begins")') < fresh.index('var holes:')
assert 'if !wantsLow || earlyPoolBase == 0 || !windowHeld' in fresh
low = function(swift, 'private static func takeLowRegion(')
assert low.index('releaseEarlyRegion(MADEIRA_EARLY_REGION_C') < low.index('let runs = freeRuns(')
assert 'guard let best = best, size >= 64 << 20' in low
assert 'let available = r.size > keep ? r.size - keep : 0' in low

c_prefix = r'''
#include <mach/mach.h>
#include <mach/vm_map.h>
#include <pthread.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "JITAllocator.h"
#define JIT_PAGE_SIZE 0x4000
#define MB (1ul << 20)
struct mapping { vm_address_t base; vm_size_t size; int owned; };
static struct mapping mappings[32];
static unsigned mapping_count, allocations, frees, queries, ports;
static int query_fail, allocate_fail, protect_fail, release_fail;
static int order(const void *a, const void *b) {
    const struct mapping *x=a,*y=b; return (x->base>y->base)-(x->base<y->base);
}
static void add(vm_address_t base, vm_size_t size, int owned) {
    assert(size && mapping_count<32);
    for(unsigned i=0;i<mapping_count;i++)
        assert(base>=mappings[i].base+mappings[i].size || base+size<=mappings[i].base);
    mappings[mapping_count++]=(struct mapping){base,size,owned};
    qsort(mappings,mapping_count,sizeof(*mappings),order);
}
static kern_return_t fake_query(vm_map_t task,vm_address_t *at,vm_size_t *size,
    vm_region_flavor_t flavor,vm_region_info_t info,mach_msg_type_number_t *count,mach_port_t *object) {
    (void)task;(void)info;(void)count;assert(flavor==VM_REGION_BASIC_INFO_64);queries++;
    if(query_fail) return KERN_FAILURE;
    for(unsigned i=0;i<mapping_count;i++) if(mappings[i].base+mappings[i].size>*at) {
        *at=mappings[i].base;*size=mappings[i].size;*object=7;return KERN_SUCCESS;
    }
    return KERN_INVALID_ADDRESS;
}
static kern_return_t fake_port(vm_map_t task,mach_port_t object) {
    (void)task;assert(object==7);ports++;return KERN_SUCCESS;
}
static kern_return_t fake_allocate(vm_map_t task,vm_address_t *at,vm_size_t size,int flags) {
    (void)task;assert(flags==VM_FLAGS_FIXED);assert(!(size & (JIT_PAGE_SIZE-1)));
    if(allocate_fail) return KERN_NO_SPACE;
    for(unsigned i=0;i<mapping_count;i++)
        if(*at<mappings[i].base+mappings[i].size && *at+size>mappings[i].base) return KERN_NO_SPACE;
    add(*at,size,1);allocations++;return KERN_SUCCESS;
}
static kern_return_t fake_protect(vm_map_t task,vm_address_t at,vm_size_t size,boolean_t max,vm_prot_t prot) {
    (void)task;(void)at;(void)size;assert(!max && prot==VM_PROT_NONE);
    return protect_fail?KERN_PROTECTION_FAILURE:KERN_SUCCESS;
}
static kern_return_t fake_free(vm_map_t task,vm_address_t at,vm_size_t size) {
    (void)task;if(release_fail) return KERN_FAILURE;
    for(unsigned i=0;i<mapping_count;i++) if(mappings[i].base==at && mappings[i].size==size) {
        assert(mappings[i].owned);mappings[i]=mappings[--mapping_count];
        qsort(mappings,mapping_count,sizeof(*mappings),order);frees++;return KERN_SUCCESS;
    }
    assert(!"attempt to free an unowned mapping");return KERN_INVALID_ADDRESS;
}
#define vm_region_64 fake_query
#define mach_port_deallocate fake_port
#define vm_allocate fake_allocate
#define vm_protect fake_protect
#define vm_deallocate fake_free
'''
c_suffix = r'''
static void reset(void) {
    memset(madeira_early_regions,0,sizeof(madeira_early_regions));
    mapping_count=allocations=frees=queries=ports=0;
    query_fail=allocate_fail=protect_fail=release_fail=0;
}
static void low_gap(vm_size_t size) {
    const vm_address_t lo=0x119000000ul,hi=0x140000000ul;
    add(lo,hi-size-lo,0);add(hi,128*MB,0);
}
static void *release_thread(void *unused) {
    (void)unused;assert(madeira_early_region_release(MADEIRA_EARLY_REGION_C,NULL,NULL)==KERN_SUCCESS);return NULL;
}
int main(void) {
    unsigned long base,size;
    reset();
    low_gap(384*MB);
    add(0x148000000ul,624*MB,0); /* Existing A hold. */
    add(0x16f000000ul,16*MB,0);  /* Main stack: must remain intact. */
    add(0x180000000ul,16*MB,0);  /* Shared region boundary. */
    madeira_early_region_claim(MADEIRA_EARLY_REGION_B,0x16f000000ul,0x180000000ul,0);
    madeira_early_region_claim(MADEIRA_EARLY_REGION_C,0x119000000ul,0x140000000ul,128*MB);
    madeira_early_region_placeholder(MADEIRA_EARLY_REGION_B,&base,&size);
    assert(base==0x170000000ul && size==256*MB);
    madeira_early_region_placeholder(MADEIRA_EARLY_REGION_C,&base,&size);
    assert(base==0x130000000ul && size==256*MB && allocations==2);
    assert(ports==queries);
    assert(madeira_early_region_release(MADEIRA_EARLY_REGION_B,NULL,NULL)==KERN_SUCCESS);
    assert(frees==1);
    madeira_early_region_placeholder(MADEIRA_EARLY_REGION_C,&base,&size);
    assert(size==256*MB); /* C survives the A/B handoff. */
    assert(madeira_early_region_release(MADEIRA_EARLY_REGION_C,&base,&size)==KERN_SUCCESS);
    assert(frees==2);
    add(base,size,0); /* The debugger/runtime now owns this address. */
    assert(madeira_early_region_release(MADEIRA_EARLY_REGION_C,NULL,NULL)==KERN_SUCCESS && frees==2);
    puts("PASS: early B/C are disjoint from A, EXE window and stack; handoff is one-shot and cannot free replacement mappings");

    reset();low_gap(189*MB);
    madeira_early_region_claim(MADEIRA_EARLY_REGION_C,0x119000000ul,0x140000000ul,128*MB);
    assert(allocations==0);
    reset();low_gap(204*MB+352*1024);
    madeira_early_region_claim(MADEIRA_EARLY_REGION_C,0x119000000ul,0x140000000ul,128*MB);
    madeira_early_region_placeholder(MADEIRA_EARLY_REGION_C,&base,&size);
    assert(size==78176*1024ul && base+size==0x140000000ul);
    puts("PASS: real-log-shaped 189 MB run cannot provide C; 204.34375 MB preserves 128 MB and supplies exactly 76.34375 MB");

    reset();
    const vm_address_t lo=0x119000000ul;
    add(lo+128*MB,16*MB,0);add(lo+224*MB,16*MB,0);
    struct madeira_early_region pick=madeira_early_region_pick(lo,lo+224*MB,128*MB);
    assert(pick.base==lo+144*MB && pick.size==80*MB);
    reset();low_gap(204*MB);
    pick=madeira_early_region_pick(0x119000000ul,0x140000000ul,4096*MB);
    assert(pick.size==0);
    puts("PASS: a separate lower run can supply the margin; oversized margin never underflows");

    for(int scenario=0;scenario<3;scenario++) {
        reset();low_gap(256*MB);
        query_fail=scenario==0;allocate_fail=scenario==1;protect_fail=scenario==2;
        madeira_early_region_claim(MADEIRA_EARLY_REGION_C,0x119000000ul,0x140000000ul,128*MB);
        madeira_early_region_placeholder(MADEIRA_EARLY_REGION_C,&base,&size);
        assert(!base && !size && allocations==frees);
    }
    reset();low_gap(256*MB);
    madeira_early_region_claim(MADEIRA_EARLY_REGION_C,0x119000000ul,0x140000000ul,128*MB);
    release_fail=1;
    assert(madeira_early_region_release(MADEIRA_EARLY_REGION_C,NULL,NULL)==KERN_FAILURE);
    madeira_early_region_placeholder(MADEIRA_EARLY_REGION_C,&base,&size);assert(size==128*MB);
    release_fail=0;
    pthread_t threads[12];
    for(unsigned i=0;i<12;i++) assert(!pthread_create(&threads[i],NULL,release_thread,NULL));
    for(unsigned i=0;i<12;i++) assert(!pthread_join(threads[i],NULL));
    assert(allocations==1 && frees==1);
    assert(madeira_early_region_release(99,NULL,NULL)==KERN_INVALID_ARGUMENT);
    puts("PASS: query/allocation/protection failures do not publish holds; failed release retains ownership; concurrent release frees once");
    return 0;
}
'''

fields = swift[swift.index('    private static let allocationLock'):swift.index('    private static func configurationValue(')]
methods = ''.join(function(swift, signature) for signature in [
    '    private static func configurationValue(',
    '    static func requestedPoolMB(',
    '    static func bindEntryProbe(',
    '    private static func logPreparedPool(',
    '    static func allocatePool(',
    '    static func detachDebugger(',
])
swift_prefix = r'''
import Foundation
typealias vm_address_t=UInt
struct JITEntryProbeRegion { var rx:UInt=0,rw:UInt=0;var size:Int=0 }
var boundRegions:[JITEntryProbeRegion]=[]
var bindings=0
func jit_entry_probe_bind(_ regions:UnsafePointer<JITEntryProbeRegion>?,_ count:Int)->Int64 {
    bindings+=1;boundRegions=Array(UnsafeBufferPointer(start:regions,count:count));return 0
}
func L(_ key: String) -> String { key }
func LF(_ key: String, _ arguments: CVarArg...) -> String { String(format:key,arguments:arguments) }
final class LogStore {
    enum Level { case info, success, error }
    static let shared=LogStore();var lines:[String]=[]
    func log(_ text:String,level:Level = .info) { lines.append(text) }
}
enum MadeiraConfig {
    static var global:[String:String]=[:],game:[String:String]=[:]
    static func gameValue(_ key:String)->String? { game[key] }
    static func get(_ key:String)->String? { global[key] }
}
var debuggerAttached=true
var detachCalls=0
func isDebuggerAttached()->Bool { debuggerAttached }
func jit26_detach() { precondition(debuggerAttached);detachCalls+=1 }
enum StikJITHelper {
    static var poolFailure:String?,exeWindowAutoMB=0
    static var poolHole:(off:Int,end:Int)?,poolHole2:(off:Int,end:Int)?,poolLow:(rx:Int,size:Int)?
    static let noDebuggerMessage="no debugger"
    static var calls=0,fail=false
'''
swift_suffix = r'''
    private static func allocateFreshPool(poolSize:Int)->(rx:UnsafeMutableRawPointer,rw:UnsafeMutableRawPointer,size:Int)? {
        calls+=1
        Thread.sleep(forTimeInterval:0.002)
        if fail { poolFailure="fixture pool failure";return nil }
        precondition(configurationValue("pool-low")=="1")
        preparedWindowMB=128
        poolHole=(off:628*1024*1024,end:638*1024*1024)
        probeBBase=0x148000000+638*1024*1024
        poolLow=(rx:0x130000000,size:76*1024*1024)
        return (UnsafeMutableRawPointer(bitPattern:0x148000000)!,UnsafeMutableRawPointer(bitPattern:0x7000000000)!,896*1024*1024)
    }
    static func reset() {
        preparedPool=nil;preparedRequest=0;preparedValues=[:];preparedWindowMB=128;terminalPoolFailure=nil;allocationValues=nil;probeBBase=nil;entryProbeBound=false;bindings=0
        poolFailure=nil;exeWindowAutoMB=0;poolHole=nil;poolHole2=nil;poolLow=nil;calls=0;fail=false
        MadeiraConfig.global=["pool-low":"1"];MadeiraConfig.game=[:];debuggerAttached=true;LogStore.shared.lines=[]
    }
    static func resetFixtureBinding() { entryProbeBound=false }
}
@main struct Check {
    static func main() {
        let mb=1024*1024
        precondition(StikJITHelper.requestedPoolMB(in:["pool":"1152"])==1152)
        precondition(StikJITHelper.requestedPoolMB(in:["pool":"255"])==896)
        precondition(StikJITHelper.requestedPoolMB(in:["pool":"1153"])==896)
        StikJITHelper.reset()
        MadeiraConfig.global=["pool-low":"0"]
        MadeiraConfig.game=["pool-low":"bad old game"]
        let pool=StikJITHelper.allocatePool(poolSize:1152*mb,configuration:["pool-low":"1"])
        precondition(pool != nil && StikJITHelper.calls==1 && MadeiraConfig.game["pool-low"]=="bad old game")
        precondition(StikJITHelper.bindEntryProbe()==0 && boundRegions.count==3)
        precondition(boundRegions[0].rx==0x148004000 && boundRegions[0].rw==0x7000004000 && boundRegions[0].size==0x4000)
        precondition(boundRegions[1].rx==0x180000000-0x4000 && boundRegions[1].rw==0x7000000000+UInt(896*mb)-0x4000)
        precondition(boundRegions[2].rx==0x130000000+UInt(76*mb)-0x4000)
        precondition(boundRegions[2].rw==0x7000000000-(0x148000000-0x130000000)+UInt(76*mb)-0x4000)
        precondition(StikJITHelper.bindEntryProbe()==0 && bindings==1)
        StikJITHelper.poolHole=nil
        StikJITHelper.resetFixtureBinding()
        precondition(StikJITHelper.bindEntryProbe()==0 && boundRegions[1].size==0x4000)
        StikJITHelper.poolHole=(off:628*mb,end:638*mb)
        print("PASS: ABC probe windows stay inside existing A/B/C, leave the first-page trampoline alone and share the correct RW distance; contiguous B is still identified")
        precondition(LogStore.shared.lines.contains { $0.contains("A+B span=917504KB usable=907264KB; C=77824KB; total usable=985088KB") })
        debuggerAttached=false
        let reused=StikJITHelper.allocatePool(poolSize:512*mb)
        precondition(reused?.rx==pool?.rx && reused?.rw==pool?.rw && StikJITHelper.calls==1)
        StikJITHelper.detachDebugger()
        precondition(detachCalls==0)
        debuggerAttached=true;StikJITHelper.detachDebugger()
        precondition(detachCalls==1)
        precondition(StikJITHelper.poolLow?.size==76*mb)
        precondition(LogStore.shared.lines.contains { $0.contains("changes apply after reopening") })
        StikJITHelper.exeWindowAutoMB=480
        precondition(StikJITHelper.allocatePool(poolSize:1152*mb)==nil && StikJITHelper.calls==1)
        precondition(StikJITHelper.poolFailure?.contains("executable window")==true)
        precondition(StikJITHelper.allocatePool(poolSize:1152*mb) != nil && StikJITHelper.calls==1)
        precondition(StikJITHelper.poolFailure==nil)
        print("PASS: entry settings snapshot is isolated; actual usable bytes exclude holes; Wine reuses mappings without debugger; incompatible larger EXE window is refused")

        StikJITHelper.reset()
        DispatchQueue.concurrentPerform(iterations:24) { _ in
            precondition(StikJITHelper.allocatePool(poolSize:1152*mb) != nil)
        }
        precondition(StikJITHelper.calls==1)
        StikJITHelper.reset();debuggerAttached=false
        precondition(StikJITHelper.allocatePool(poolSize:1152*mb)==nil && StikJITHelper.calls==0)
        debuggerAttached=true
        precondition(StikJITHelper.allocatePool(poolSize:1152*mb) != nil && StikJITHelper.calls==1)
        StikJITHelper.reset();StikJITHelper.fail=true
        precondition(StikJITHelper.allocatePool(poolSize:1152*mb)==nil)
        precondition(StikJITHelper.allocatePool(poolSize:1152*mb)==nil && StikJITHelper.calls==1)
        print("PASS: concurrent entry/Play callers allocate once; absent debugger performs no BRK; failed production allocation cannot repeatedly consume mappings")
    }
}
'''

with tempfile.TemporaryDirectory(prefix='mdeck-entry-pool-') as directory:
    folder = Path(directory)
    c_file = folder / 'Check.c'
    c_file.write_text(c_prefix + helpers + c_suffix)
    binary = folder / 'native-check'
    subprocess.run(['xcrun', 'clang', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I', str(app), str(c_file), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
    swift_file = folder / 'Check.swift'
    swift_file.write_text(swift_prefix + fields + methods + swift_suffix)
    binary = folder / 'swift-check'
    subprocess.run(['xcrun', 'swiftc', '-parse-as-library', str(swift_file), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    subprocess.run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios18.0',
                    '-isysroot', sdk, '-fsyntax-only', str(app / 'JITAllocator.c')], check=True)
    stubs = folder / 'IOSDependencies.swift'
    stubs.write_text('''import UIKit
func L(_ key: String) -> String { key }
func LF(_ key: String, _ arguments: CVarArg...) -> String { String(format:key,arguments:arguments) }
final class LogStore {
    enum Level { case info, success, error, debug }
    static let shared=LogStore()
    func log(_ text:String,level:Level = .info) {}
}
enum MadeiraConfig {
    static func gameValue(_ key:String)->String? { nil }
    static func get(_ key:String)->String? { nil }
    static func flag(_ key:String)->Bool { true }
}
struct SigningStatus { static var current:Self { Self() };var debugged:Bool { true } }
func isDebuggerAttached()->Bool { true }
''')
    subprocess.run(['xcrun', 'swiftc', '-typecheck', '-sdk', sdk, '-target', 'arm64-apple-ios18.0',
                    '-import-objc-header', str(app / 'JITAllocator.h'), str(stubs),
                    str(app / 'StikJITHelper.swift')], check=True)
print('PASS: production native early holds and full Swift allocator typecheck against iOS SDK')
print('Synthetic VM/debugger checks only; A/B/C capacity and real handoff on iPad remain UNRUN.')
