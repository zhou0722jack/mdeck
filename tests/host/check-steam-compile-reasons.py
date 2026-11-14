#!/usr/bin/env python3
"""Actions-only: actual classification ABI, producer RAII and native lifecycle.
Fixtures never run Wine or pause application threads.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile

assert os.environ.get('GITHUB_ACTIONS')=='true','Run this check in GitHub Actions'
root=Path(__file__).resolve().parents[2]
patches=root/'build/fex-patches'

core=r'''
#include "steam_compile_reason_abi.h"
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <pthread.h>
static struct sr_bridge *b;
static struct sr_fingerprint bytes(unsigned value) {
 struct sr_fingerprint f=sr_fingerprint_init();uint8_t code[]={0x90,(uint8_t)value};
 sr_fingerprint_block(&f,0x10000);sr_fingerprint_inst(&f,0x10000,code,2);return f;
}
static struct sr_ticket begin(void){return sr_begin(b,1,0xe8,0x23c,1);}
static struct sr_key key={.instance=1,.owner=5,.rip=0x10000};
static void note(struct sr_key k,struct sr_fingerprint f,uint64_t gen){assert(sr_finish(b,begin(),k,f,gen,SR_GENERATED,100));}
static void* writer(void* arg) {
 uintptr_t n=(uintptr_t)arg;
 for(unsigned i=0;i<10000;i++) {
  struct sr_key k={.instance=1,.owner=100+n,.rip=0x10000+i*16};
  sr_finish(b,sr_begin(b,1,0xe8,(unsigned)n+4,1),k,bytes(i),10,SR_GENERATED,100);
 }
 return NULL;
}
int main(void){
 b=calloc(1,sizeof(*b));assert(b);b->active_epoch=1;
 assert(!sr_begin(b,0,1,1,1).epoch);
 note(key,bytes(1),10);assert(b->kind[SR_FIRST].count==1);
 note(key,bytes(1),10);assert(b->kind[SR_SAME_GENERATION].count==1);
 note(key,bytes(1),11);assert(b->kind[SR_NEW_GENERATION].count==1);
 note(key,bytes(2),11);assert(b->kind[SR_CHANGED].count==1);
 note(key,bytes(3),12);assert(b->kind[SR_CHANGED].count==2);
 struct sr_fingerprint shape=bytes(3);sr_fingerprint_block(&shape,0x10002);
 note(key,shape,13);assert(b->shape_changed==1&&b->kind[SR_UNKNOWN].count==1);
 note(key,shape,14);assert(b->kind[SR_NEW_GENERATION].count==2);
 // Distinct manager/instance/mode/MaxInst can never alias the reason history.
 struct sr_key other=key;other.owner++;note(other,bytes(3),10);
 other=key;other.mode=1;note(other,bytes(3),10);
 other=key;other.max_inst=1;note(other,bytes(3),10);
 assert(sr_finish(b,sr_begin(b,2,0xe8,0x23c,2),key,bytes(3),10,SR_GENERATED,100));
 assert(b->kind[SR_FIRST].count==5);
 // No record of a successful generation for a race, failure or delivery.
 uint64_t history=b->history_used;
 for(unsigned outcome=SR_RACED;outcome<SR_OUTCOMES;outcome++)assert(sr_finish(b,begin(),key,bytes(9),99,outcome,100));
 assert(b->history_used==history);
 struct sr_ticket old=begin(),newer=begin();
 assert(sr_finish(b,newer,key,shape,15,SR_GENERATED,100));
 assert(sr_finish(b,old,key,bytes(0),16,SR_GENERATED,100));assert(b->out_of_order==1);
 // Late old completions must not overwrite the newer fingerprint baseline.
 note(key,shape,16);assert(b->kind[SR_NEW_GENERATION].count==4);
 uint64_t attempts=b->attempts;
 old=begin();b->active_epoch=0;assert(!sr_finish(b,old,key,bytes(0),99,SR_GENERATED,100));
 b->active_epoch=2;assert(!sr_finish(b,old,key,bytes(0),99,SR_GENERATED,100)&&b->attempts==attempts);
 note(key,bytes(1),10);assert(b->kind[SR_FIRST].count==6); // new window, not lifetime first
 assert(sr_lock(b));assert(!sr_finish(b,begin(),key,bytes(1),10,SR_GENERATED,100));sr_unlock(b);assert(b->dropped==1);
 struct sr_fingerprint bad=bytes(1);bad.invalid=1;note(key,bad,10);assert(b->missing_fingerprint==1);
 note(key,bytes(1),0);assert(b->missing_generation==1);
 struct sr_fingerprint limit=sr_fingerprint_init();uint8_t inst[15]={0};
 for(unsigned i=0;i<2000;i++)sr_fingerprint_inst(&limit,0x10000+i*15,inst,15);
 assert(limit.invalid&&limit.bytes<=SR_MAX_BYTES);
 limit=sr_fingerprint_init();sr_fingerprint_inst(&limit,UINT64_MAX,inst,1);assert(limit.invalid);
 // A full bounded probe chain returns unknown without evicting/forgetting.
 memset(b,0,sizeof(*b));b->active_epoch=3;
 unsigned found=0;uint64_t a=0x10000;
 for(;found<SR_PROBES+1;a++) {
  struct sr_key k=key;k.rip=a;if(sr_index(k)!=0)continue;
  note(k,bytes(1),10);found++;
 }
 assert(b->kind[SR_FIRST].count==SR_PROBES&&b->history_full==1&&b->kind[SR_UNKNOWN].count==1);
 struct sr_key first=b->history[0].key;note(first,bytes(1),11);assert(b->kind[SR_NEW_GENERATION].count==1);
 // Every recorded generated event reconciles to one exclusive classification.
 uint64_t sum=0;for(unsigned i=0;i<SR_KINDS;i++)sum+=b->kind[i].count;
 assert(sum==b->outcome[SR_GENERATED]&&sum==b->classified);
 b->attempts=SR_MAX_COMPLETIONS;assert(!sr_finish(b,begin(),key,bytes(1),1,SR_GENERATED,100));
 // Shared history uses try-locks under concurrent compilers, no waiting.
 memset(b,0,sizeof(*b));b->active_epoch=4;
 pthread_t workers[4];for(uintptr_t i=0;i<4;i++)assert(!pthread_create(&workers[i],NULL,writer,(void*)i));
 for(unsigned i=0;i<4;i++)pthread_join(workers[i],NULL);
 sum=0;for(unsigned i=0;i<SR_KINDS;i++)sum+=b->kind[i].count;
 assert(sum==b->classified&&sum==b->attempts&&b->attempts+b->dropped==40000);
 free(b);puts("PASS compile classification: first/changed/new-generation/same-generation, shape uncertainty, instance/owner/mode isolation, failed/raced/delivery exclusion, epoch cancellation, bounded overflow, concurrent reconciliation");
}
'''

producer=r'''
#include <cassert>
#include <cstdlib>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include "steam_compile_reason_abi.h"
#define _WIN32 1
#define FEX_IOS_HOST 1
#include "SteamCompileReason.h"
#undef _WIN32
alignas(16) static uint64_t teb[32]{};
extern "C" uint64_t mdeck_steam_probe_teb(){return (uintptr_t)teb;}
int main(){
 using namespace FEXCore::CompileReason;
 auto* b=(sr_bridge*)calloc(1,sizeof(sr_bridge));assert(b);
 b->magic=SR_MAGIC;b->bytes=sizeof(*b);b->frequency=24000000;b->active_epoch=7;
 teb[0x40/8]=0xe8;teb[0x48/8]=0x23c;
 Initialize(nullptr,1);Initialize("junk",1);Initialize("fffffffffffffffff",1);assert(!Bridge);
 char pointer[32];snprintf(pointer,sizeof(pointer),"%llx",(unsigned long long)(uintptr_t)b);
 Initialize(pointer,1);assert(Bridge==b&&Instance&&b->attached==1);
 assert(NextId()!=NextId());
 const uint8_t code[]={0x90};
 { Capture r(1,0x10000,0,0,false);assert(r.Active());r.Block(0x10000);r.Instruction(0x10000,code,1);r.Finish(10,SR_GENERATED); }
 { Capture r(1,0x10000,0,0,false);r.Block(0x10000);r.Instruction(0x10000,code,1);r.Finish(11,SR_GENERATED); }
 assert(b->kind[SR_FIRST].count==1&&b->kind[SR_NEW_GENERATION].count==1);
 {Capture r(1,0x10000,0,0,false);r.Finish(0,SR_RACED);}
 {Capture r(1,0x10000,0,0,false);}
 {Capture r(1,0x10000,0,0,true);assert(!r.Active());r.Finish(99,SR_GENERATED);}
 assert(b->outcome[SR_RACED]==1&&b->outcome[SR_FAILED]==1&&b->outcome[SR_DELIVERY]==1);
 {Capture r(1,0x10000,0,0,false);r.Unsupported();r.Finish(11,SR_GENERATED);}
 assert(b->missing_fingerprint==1);
 const auto before=b->attempts;
 {Capture r(1,0x10000,0,0,false);b->active_epoch=0;r.Finish(11,SR_GENERATED);}
 assert(b->attempts==before);
 {Capture r(1,0x10000,0,0,false);assert(!r.Active());}
 assert(b->attempts==before);
 free(b);puts("PASS actual PE producer: default off, independent shared bridge, decoder fingerprint, output generation, RAII failure, races, delivery and stop");
}
'''

native=r'''
#include <pthread.h>
#include <assert.h>
#include <errno.h>
static int failed_create(pthread_t* thread,const pthread_attr_t* attr,void*(*fn)(void*),void* p){(void)thread;(void)attr;(void)fn;(void)p;return EAGAIN;}
#define pthread_create failed_create
#include "steam_compile_log.c"
#undef pthread_create
int main(void){
 assert(!cr_bridge);ios_steam_compile_log_configure(1);assert(!cr_bridge); // foreground gate
 ios_steam_compile_log_set_active(1);ios_steam_compile_log_configure(0);assert(!cr_bridge);
 ios_steam_compile_log_configure(1);assert(cr_bridge&&!cr_bridge->active_epoch&&!cr_worker_started);
 cr_worker_started=1;ios_steam_compile_log_configure(1);assert(cr_bridge->active_epoch);
 uint64_t epoch=cr_bridge->active_epoch;
 struct sr_fingerprint f=sr_fingerprint_init();uint8_t code[]={0x90};
 sr_fingerprint_block(&f,0x10000);sr_fingerprint_inst(&f,0x10000,code,1);
 struct sr_ticket ticket=sr_begin(cr_bridge,1,0xe8,0x23c,1);
 assert(sr_finish(cr_bridge,ticket,(struct sr_key){.owner=5,.rip=0x10000},f,10,SR_GENERATED,24000));
 cr_report(epoch,cr_started,cr_begun_start,cr_dropped_start,"fixture-complete");
 struct cr_report r;assert(cr_snapshot(cr_bridge,epoch,&r)&&r.kind[SR_FIRST].count==1);
 assert(sr_lock(cr_bridge));assert(!cr_snapshot(cr_bridge,epoch,&r));sr_unlock(cr_bridge);
 assert(!cr_stop_reason(1,1,0));assert(!strcmp(cr_stop_reason(1,1+CR_DURATION_NS,0),"duration-complete"));
 assert(!strcmp(cr_stop_reason(1,1,SR_MAX_COMPLETIONS),"event-budget"));
 assert(!strcmp(cr_stop_reason(2,1,0),"clock-error"));
 ios_steam_compile_log_configure(0);assert(!cr_bridge->active_epoch);
 ios_steam_compile_log_configure(1);assert(cr_bridge->active_epoch!=epoch&&!cr_bridge->attempts);
 assert(!sr_finish(cr_bridge,ticket,(struct sr_key){.owner=5,.rip=0x10000},f,99,SR_GENERATED,24000));
 ios_steam_compile_log_set_active(0);assert(!cr_bridge->active_epoch);
 ios_steam_compile_log_set_active(1);assert(!cr_bridge->active_epoch);
 puts("PASS native compile logger: independent default off, foreground/manual/session stop, no automatic resume, bounded duration/event budget, report and old-scope isolation");
}
'''

with tempfile.TemporaryDirectory(prefix='mdeck-reasons-') as tmp:
    work=Path(tmp)
    deps=work/'include/FEXCore/Utils';deps.mkdir(parents=True)
    for name in ['SteamCompileReason.h','steam_compile_reason_abi.h']:
        shutil.copyfile(patches/name,deps/name)
    for name,source,cpp in [('classify',core,False),('producer',producer,True),('native',native,False)]:
        src=work/(name+('.cpp' if cpp else '.c'));src.write_text(source)
        for mode in (['wow64','arm64ec'] if cpp else ['host']):
            out=work/(name+'-'+mode)
            flags=['xcrun','clang++' if cpp else 'clang','-std=c++20' if cpp else '-std=c11',
                   '-O1','-g','-Wall','-Wextra','-Werror','-Wno-unused-function','-fsanitize=address,undefined',
                   '-fno-sanitize-recover=all','-pthread','-I'+str(deps),'-I'+str(root/'build/ntdll-unix')]
            if mode=='arm64ec':flags.append('-DARCHITECTURE_arm64ec')
            subprocess.run(flags+[str(src),'-o',str(out)],check=True)
            result=subprocess.run([str(out)],text=True,capture_output=True,timeout=45)
            if result.returncode:print(result.stdout,result.stderr);result.check_returncode()
            print(result.stdout,end='')
            if name=='native':
                assert 'reason=fixture-complete' in result.stderr
                assert 'kind=first-observed count=1 total_wall_ms=1.000000' in result.stderr
                assert 'first_observed=1' in result.stderr and 'reason=worker-create-failed' in result.stderr
    # Real iPhoneOS compiler sees the complete standalone source.
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    subprocess.run(['xcrun','--sdk','iphoneos','clang','-target','arm64-apple-ios17.0','-isysroot',sdk,
                    '-std=c11','-Wall','-Wextra','-Werror','-fsyntax-only',str(root/'build/ntdll-unix/steam_compile_log.c')],check=True)
    # Full patch chain on copies of the actual pin, preserving local FEX.
    source=work/'patched';source.mkdir();subprocess.run(['git','init','-q',str(source)],check=True)
    names=set()
    for p in patches.glob('*.patch'):names.update(re.findall(r'^--- a/(.+)$',p.read_text(),re.M))
    for name in names:
        out=source/name;out.parent.mkdir(parents=True,exist_ok=True)
        out.write_bytes(subprocess.check_output(['git','-C',str(root/'FEX'),'show','HEAD:'+name]))
    for p in sorted(patches.glob('*.patch')):
        subprocess.run(['git','-C',str(source),'apply','--check',str(p)],check=True)
        subprocess.run(['git','-C',str(source),'apply',str(p)],check=True)
    for p in sorted(patches.glob('*.patch')):subprocess.run(['git','-C',str(source),'apply','--reverse','--check',str(p)],check=True)
    core_text=(source/'FEXCore/Source/Interface/Core/Core.cpp').read_text()
    assert 'Reason->Instruction(InstAddress, DecodedInfo->InstBytes, DecodedInfo->InstSize)' in core_text
    assert 'Reason->Block(Block.Entry)' in core_text and 'Reason && HasCustomIR' in core_text
    assert core_text.index('Reason.Finish(0, SR_RACED)')<core_text.index('auto DebugData = fextl::make_unique<FEXCore::Core::DebugData>();',core_text.index('ContextImpl::CompileCodeResult ContextImpl::CompileCode'))
    assert 'Reason.Finish(MDECK_REASON_GENERATION(CompiledCode),' in core_text
    backend=(source/'FEXCore/Source/Interface/Core/CPUBackend.cpp').read_text()
    pos=backend.index('auto Buffer = fextl::make_shared<CodeBuffer>(Size);')
    assert backend.index('Buffer->MDeckReasonGeneration =',pos)<backend.index('Latest = Buffer;',pos)
    jit=(source/'FEXCore/Source/Interface/Core/JIT/JIT.cpp').read_text()
    pos=jit.index('if ((GetCursorOffset() + TempSize) > CurrentCodeBuffer->UsableSize())')
    assert jit.index('CodeData.MDeckReasonGeneration = CurrentCodeBuffer->MDeckReasonGeneration;',pos)>jit.index('CTX->ClearCodeCache(ThreadState);',pos)
    for path in ['WOW64','ARM64EC']:
        text=(source/f'Source/Windows/{path}/Module.cpp').read_text()
        assert 'CompileReason::Initialize(getenv("MADEIRA_COMPILE_REASON_BRIDGE"),' in text
    # Native builds must not gain PE symbol dependencies from the header.
    noop=work/'noop.cpp';noop.write_text('#include "SteamCompileReason.h"\nint main(){MDECK_COMPILE_CAPTURE(r,unused,0,0,0,false);r.Finish(0,SR_FAILED);}\n')
    subprocess.run(['xcrun','clang++','-std=c++20','-Wall','-Wextra','-Werror','-I'+str(deps),str(noop),'-o',str(work/'noop')],check=True)
    subprocess.run([str(work/'noop')],check=True)

bridge=(root/'app/Madeira/WineProcessBridge.m').read_text()
assert bridge.index('unsetenv("MADEIRA_STEAM_COMPILE_REASONS")')<bridge.index('setenv(k.UTF8String, v.UTF8String, 1);')
assert bridge.index('getenv("MADEIRA_STEAM_COMPILE_REASONS")')>bridge.index('dup2(logfd, STDERR_FILENO);')
assert bridge.count('ios_steam_compile_log_configure(0);')==2
ui=(root/'app/Madeira/Library.swift').read_text()
assert 'SteamCompileReasonSettings.text(file.text, enabled: enabled)' in ui
assert 'Button("Stop compilation reason logging") { winios_compile_reason_stop() }' in ui
print('PASS full patch-chain, decoder byte provenance, buffer identity before publication, independent UI/env/lifecycle, iPhoneOS syntax and native no-op')
print('UNRUN: complete FEX PE compile/link, device classifications, coverage and diagnostic overhead')
