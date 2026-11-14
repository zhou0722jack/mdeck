#!/usr/bin/env python3
"""Production bounded sampler with controlled Mach calls; never suspend Wine.
Run only in GitHub Actions. Separate iPhoneOS syntax checks cover the full file.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
native = root / 'build/ntdll-unix'
core = r'''
#include "steam_hotspot.h"
#include <assert.h>
struct fake { uint64_t time; int suspend_error,state_error,resume_errors,suspends,states,resumes,held; };
static uint64_t now(void *p) { return ((struct fake *)p)->time; }
static int suspend_one(void *p,uintptr_t t) { struct fake *f=p;(void)t; f->suspends++;if(f->suspend_error)return 1;f->held=1;return 0; }
static int read_one(void *p,uintptr_t t,struct sh_registers *out) { struct fake *f=p;(void)t;assert(f->held);f->states++;f->time+=1000;out->pc=42;return f->state_error; }
static int resume_one(void *p,uintptr_t t) {struct fake *f=p;(void)t;assert(f->held);f->resumes++;if(f->resume_errors-- >0)return 1;f->held=0;return 0;}
int main(void) {
 struct fake f={0};struct sh_capture_ops ops={now,suspend_one,read_one,resume_one,&f};
 struct sh_capture c=sh_capture_thread(&ops,3);assert(c.suspended&&c.state_ok&&c.resumed&&!f.held&&f.resumes==1&&c.held_ns==1000);
 f=(struct fake){.state_error=1};c=sh_capture_thread(&ops,3);assert(c.suspended&&!c.state_ok&&c.resumed&&!f.held&&f.resumes==1);
 f=(struct fake){.suspend_error=1};c=sh_capture_thread(&ops,3);assert(!c.suspended&&!f.states&&!f.resumes);
 f=(struct fake){.resume_errors=1};c=sh_capture_thread(&ops,3);assert(c.resumed&&!f.held&&c.resume_tries==2);
 f=(struct fake){.resume_errors=9};c=sh_capture_thread(&ops,3);assert(!c.resumed&&c.resume_tries==3&&f.resumes==3);
 assert(sh_phase(100,100,0,0)==0&&sh_phase(100,100+SH_DELAY_NS,0,0)==1);
 assert(sh_phase(100,99,0,0)==-1&&sh_phase(100,100+SH_DELAY_NS+SH_DURATION_NS,0,0)==-1);
 assert(sh_phase(100,100+SH_DELAY_NS,SH_MAX_SAMPLES,0)==-1&&sh_phase(100,100+SH_DELAY_NS,0,SH_TOTAL_HOLD_NS)==-1);
 assert(!sh_may_sample(1,1,2,0,100)&&!sh_may_sample(2,1,2,0,100));
 assert(!sh_may_sample(3,1,0,0,100)&&!sh_may_sample(3,1,2,1,100)&&!sh_may_sample(3,1,2,0,1.99));
 assert(sh_may_sample(3,1,2,0,2));
 assert(sh_classify(0x1400,0x1400,0x100,0,0,0,0)==SH_JIT_AB);
 assert(sh_classify(0x1400,0x1400,0x100,0,1,0,0)==SH_PE);
 assert(sh_classify(0x1200,0x1400,0x100,1,0,0,0)==SH_JIT_C);
 assert(sh_classify(0x1300,0x1400,0x100,0,0,0,0)==SH_UNKNOWN);
 assert(sh_classify(0x1500,0x1400,0x100,0,0,0,1)==SH_HOST);
 assert(sh_classify(UINT64_MAX,UINT64_MAX-20,10,0,0,0,0)==SH_UNKNOWN);
 struct sh_bucket buckets[3]={0};unsigned over=0;sh_bucket_note(buckets,3,"early-a",1,&over);sh_bucket_note(buckets,3,"early-b",2,&over);sh_bucket_note(buckets,3,"early-c",3,&over);
 for(unsigned i=0;i<100;i++)sh_bucket_note(buckets,3,"late-hot",4,&over);
 unsigned found=0,sum=0;for(unsigned i=0;i<3;i++){sum+=buckets[i].hits;if(!strcmp(buckets[i].desc,"late-hot")){found++;assert(buckets[i].hits>=100&&buckets[i].hits-buckets[i].error<=100);}}
 assert(found==1&&sum==103&&over>0);sh_bucket_note(buckets,0,"zero",0,&over);
 puts("PASS production hotspot core: suspend/read/resume failure paths, retry limit, time/sample budgets, self/main exclusion, separate A/B/C and PE classification, late hot locations and explicit approximation error");
}
'''

backend = r'''
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <mach/mach_vm.h>
#include <mach/thread_policy.h>
#include <mach/arm/thread_status.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <dlfcn.h>
#include <errno.h>
#include <time.h>
#include <unistd.h>
#include <sys/qos.h>
#include <assert.h>
#include <stdarg.h>
static uint64_t fake_time=1000000000ull;
static unsigned round_no,ports_freed,arrays_freed,suspend_calls,resume_calls,held,read_error,slow_capture,cancel_capture;
static unsigned selected[10];
static kern_return_t f_tasks(task_t,thread_act_array_t*,mach_msg_type_number_t*);
static kern_return_t f_info(thread_act_t,thread_flavor_t,thread_info_t,mach_msg_type_number_t*);
static kern_return_t f_suspend(thread_act_t);
static kern_return_t f_resume(thread_act_t);
static kern_return_t f_state(thread_act_t,thread_state_flavor_t,thread_state_t,mach_msg_type_number_t*);
static kern_return_t f_policy(thread_t,thread_policy_flavor_t,thread_policy_t,mach_msg_type_number_t*,boolean_t*);
static kern_return_t f_free(ipc_space_t,mach_port_name_t);
static kern_return_t f_array(vm_map_t,vm_address_t,vm_size_t);
static pthread_t f_pthread(mach_port_t);
static int f_name(pthread_t,char*,size_t);
static int f_id(pthread_t,uint64_t*);
static uint64_t f_time(void);
static int f_dladdr(const void*,Dl_info*);
static int f_lock(pthread_mutex_t*);
static int f_log(int,const char*,...);
static int f_create(pthread_t*,const pthread_attr_t*,void*(*)(void*),void*);
#define task_threads f_tasks
#define thread_info f_info
#define thread_suspend f_suspend
#define thread_resume f_resume
#define thread_get_state f_state
#define thread_policy_get f_policy
#define mach_port_deallocate f_free
#define vm_deallocate f_array
#define pthread_from_mach_thread_np f_pthread
#define pthread_getname_np f_name
#define pthread_threadid_np f_id
#define mach_absolute_time f_time
#define dladdr f_dladdr
#define pthread_mutex_lock f_lock
#define dprintf f_log
#define pthread_create f_create
#include "steam_hotspot.c"
#undef pthread_mutex_lock
#undef dprintf
pthread_key_t ios_teb_tls_key;
void *ios_jit_rx_base_global=(void*)0x140000000ull;
size_t ios_jit_pool_size_global=0x10000000;
int ios_jit_low_contains(uintptr_t a){assert(!held);return a>=0x120000000ull&&a<0x130000000ull;}
int ios_jit_pool_image_pc(uintptr_t a,uintptr_t *out){assert(!held);if(a==0x140010000ull){*out=0x7200100000ull;return 1;}return 0;}
static kern_return_t f_tasks(task_t task,thread_act_array_t *out,mach_msg_type_number_t *n){(void)task;assert(!held);static thread_t list[]={1,2,3,4,5,6,7};*out=list;*n=7;round_no++;return 0;}
static kern_return_t f_info(thread_act_t t,thread_flavor_t flavor,thread_info_t out,mach_msg_type_number_t *n){(void)n;assert(!held);
 if(flavor==THREAD_IDENTIFIER_INFO){thread_identifier_info_t i=(void*)out;memset(i,0,sizeof(*i));i->thread_id=100+t;return 0;}
 thread_basic_info_t b=(void*)out;memset(b,0,sizeof(*b));b->run_state=TH_STATE_RUNNING;b->suspend_count=t==5;
 b->user_time.microseconds=1000+round_no*(t==3?16000:t==4?12000:50000);return 0;}
static kern_return_t f_suspend(thread_act_t t){assert(!held&&t!=1&&t!=2&&t!=5&&t!=6&&t!=7);held=t;selected[t]++;suspend_calls++;return 0;}
static kern_return_t f_resume(thread_act_t t){assert(held==t);held=0;resume_calls++;return 0;}
static kern_return_t f_state(thread_act_t t,thread_state_flavor_t flavor,thread_state_t out,mach_msg_type_number_t *n){(void)flavor;(void)n;assert(held==t);
 fake_time+=slow_capture?SH_ONE_HOLD_NS+1:100000;if(cancel_capture){atomic_store(&sh_enabled,0);atomic_fetch_add(&sh_epoch,1);}
 if(read_error&&t==3)return KERN_FAILURE;
 arm_thread_state64_t *s=(void*)out;memset(s,0,sizeof(*s));__darwin_arm_thread_state64_set_pc_fptr(*s,(void*)(uintptr_t)(t==3?0x120001000ull:0x100001000ull));return 0;}
static kern_return_t f_free(ipc_space_t task,mach_port_name_t port){(void)task;(void)port;assert(!held);ports_freed++;return 0;}
static kern_return_t f_array(vm_map_t task,vm_address_t address,vm_size_t size){(void)task;(void)address;assert(size==7*sizeof(thread_t)&&!held);arrays_freed++;return 0;}
static kern_return_t f_policy(thread_t t,thread_policy_flavor_t flavor,thread_policy_t out,mach_msg_type_number_t *count,boolean_t *get_default){(void)flavor;(void)out;(void)count;assert(!held);*get_default=t!=7;return 0;}
static pthread_t f_pthread(mach_port_t p){assert(!held);return(pthread_t)(uintptr_t)p;}
static int f_name(pthread_t p,char *out,size_t n){assert(!held);unsigned t=(unsigned)(uintptr_t)p;snprintf(out,n,"%s",t==3||t==5?"Chrome_InProcRendererThread":t==6?"AudioIO":"");return 0;}
static int f_id(pthread_t p,uint64_t *id){(void)p;assert(!held);*id=101;return 0;}
static uint64_t f_time(void){return fake_time;}
static int f_dladdr(const void *address,Dl_info *out){assert(!held);if((uintptr_t)address==0x100001000ull){*out=(Dl_info){.dli_fname="/private/path/Madeira.debug.dylib",.dli_fbase=(void*)0x100000000ull,.dli_sname="native_worker",.dli_saddr=(void*)0x100001000ull};return 1;}return 0;}
static int f_lock(pthread_mutex_t *p){assert(!held);return pthread_mutex_lock(p);}
static int f_log(int fd,const char *format,...){assert(!held);va_list ap;va_start(ap,format);int n=vdprintf(fd,format,ap);va_end(ap);return n;}
static int f_create(pthread_t *t,const pthread_attr_t *attr,void*(*fn)(void*),void *p){(void)t;(void)attr;(void)fn;(void)p;return EAGAIN;}
static struct sh_run fresh(void){round_no=ports_freed=arrays_freed=suspend_calls=resume_calls=held=read_error=slow_capture=cancel_capture=0;memset(selected,0,sizeof(selected));fake_time=1000000000ull+SH_DELAY_NS;atomic_store(&sh_main_id,102);atomic_store(&sh_active,1);atomic_store(&sh_enabled,1);atomic_store(&sh_epoch,7);sh_timebase=(mach_timebase_info_data_t){1,1};return(struct sh_run){.epoch=7,.started=1000000000ull};}
int main(void){
 struct sh_run r=fresh();assert(!sh_tick(&r)&&!r.attempts);fake_time+=SH_TICK_NS;assert(!sh_tick(&r));
 assert(r.attempts==2&&r.success==2&&suspend_calls==2&&resume_calls==2&&!held);
 assert(selected[3]==1&&selected[4]==1&&ports_freed==14&&arrays_freed==2);
 assert(r.threads_used==2&&r.threads[0].states[SH_JIT_C]==1&&r.threads[1].states[SH_HOST]==1);
 sh_report(&r,"fixture-complete");
 char desc[176];struct sh_candidate c={0};
 assert(sh_describe(c,(struct sh_registers){.pc=0x140001000ull},desc)==SH_JIT_AB);
 assert(sh_describe(c,(struct sh_registers){.pc=0x140010000ull},desc)==SH_PE);
 assert(sh_describe(c,(struct sh_registers){.pc=0x130001000ull},desc)==SH_UNKNOWN);
 r=fresh();sh_tick(&r);fake_time+=SH_TICK_NS;read_error=1;assert(!sh_tick(&r));assert(r.state_failed==1&&r.success==1&&resume_calls==2&&!held);
 r=fresh();sh_tick(&r);fake_time+=SH_TICK_NS;slow_capture=1;assert(!strcmp(sh_tick(&r),"single-hold-budget"));assert(r.attempts==1&&resume_calls==1&&!held&&ports_freed==14);
 r=fresh();sh_tick(&r);fake_time+=SH_TICK_NS;cancel_capture=1;assert(!sh_tick(&r));assert(r.attempts==1&&!r.success&&resume_calls==1&&!held&&ports_freed==14);
 r=fresh();sh_tick(&r);fake_time+=SH_TICK_NS;r.attempts=SH_MAX_SAMPLES;assert(!sh_tick(&r)&&!suspend_calls);
 r=fresh();ios_steam_hotspot_set_active(0);assert(!atomic_load(&sh_enabled));ios_steam_hotspot_set_active(1);assert(!atomic_load(&sh_enabled));
 ios_steam_hotspot_configure(0);uint64_t e=atomic_load(&sh_epoch);assert(!atomic_load(&sh_enabled));
 sh_worker_started=0;ios_steam_hotspot_configure(1);assert(!atomic_load(&sh_enabled)&&atomic_load(&sh_epoch)>e);
 puts("PASS production hotspot backend: busy CEF plus unnamed native selection, self/main/suspended exclusion, no lookup/log/locks while held, all ports released, failure/cancel resume pairing, A/B/C and host classification, limits, foreground gating and worker-create failure");
}
'''

with tempfile.TemporaryDirectory() as folder:
    d = Path(folder)
    for name, text in [('core', core), ('backend', backend)]:
        src, exe = d / (name + '.c'), d / name
        src.write_text(text)
        subprocess.run(['xcrun','clang','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function',
                        '-fsanitize=address,undefined','-pthread','-I'+str(native),str(src),'-o',str(exe)],check=True)
        result = subprocess.run([str(exe)],text=True,capture_output=True,check=True,timeout=30)
        print(result.stdout,end='')
        if name == 'backend':
            assert 'reason=fixture-complete' in result.stderr and 'jit_C=1' in result.stderr and 'host=1' in result.stderr
            assert '/private/path/' not in result.stderr
            assert 'reason=worker-create-failed' in result.stderr
    sdk = subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    subprocess.run(['xcrun','--sdk','iphoneos','clang','-target','arm64-apple-ios17.0','-isysroot',sdk,
                    '-std=c11','-Wall','-Wextra','-Werror','-fsyntax-only',str(native/'steam_hotspot.c')],check=True)
print('PASS full production hotspot source: iPhoneOS syntax; fixtures never suspend real Wine/app threads')

bridge = (root/'app/Madeira/WineProcessBridge.m').read_text()
assert bridge.index('unsetenv("MADEIRA_STEAM_HOTSPOT")') < bridge.index('setenv(k.UTF8String, v.UTF8String, 1);')
assert bridge.index('e = getenv("MADEIRA_STEAM_HOTSPOT");') > bridge.index('dup2(logfd, STDERR_FILENO);')
assert bridge.count('ios_steam_hotspot_configure(0);') == 2
winios = (root/'app/Madeira/Winios/Winios.m').read_text()
assert 'void winios_hotspot_stop(void) { ios_steam_hotspot_configure(0); }' in winios
assert 'ios_steam_hotspot_set_active(0);' in winios and 'ios_steam_hotspot_set_active(1);' in winios
assert 'winios_hotspot_prepare()' in (root/'app/Madeira/MadeiraApp.swift').read_text()
build = (native/'build.sh').read_text()
assert 'compile_one "$BUILD_DIR/steam_hotspot.c" "steam_hotspot"' in build
assert '"$OBJ_DIR/steam_hotspot.o"' in build
print('PASS integration: independent default-off key, session cleanup, manual stop, foreground gate and native archive membership')
