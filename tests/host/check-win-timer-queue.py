#!/usr/bin/env python3
"""Execute the production timer request for failed and available GUI queues."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'build/wineserver/queue_ios.c').read_text()
start = source.index('DECL_HANDLER(set_win_timer)')
handler = source[start:source.index('/* kill a window timer */', start)]
fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef unsigned user_handle_t;
typedef uint64_t lparam_t;
struct timer { user_handle_t win; unsigned msg; lparam_t id,lparam; } stored;
struct msg_queue { lparam_t next_timer_id; } queue;
struct thread { void *process; struct msg_queue *queue; unsigned id,desktop; } caller,target;
static struct thread *current=&caller;
struct request { user_handle_t win; lparam_t id; unsigned msg,rate; lparam_t lparam; } request;
struct reply { lparam_t id; } reply;
static unsigned error,queue_error;
static int lookups,allocations,freed,released,existing,exhausted,allocation_fails,valid_window;
#define STATUS_INVALID_HANDLE 0xc0000008u
#define STATUS_ACCESS_DENIED 0xc0000022u
#define STATUS_NO_MEMORY 0xc0000017u
#define ERROR_NO_MORE_USER_HANDLES 1158
#define DECL_HANDLER(name) static void name(const struct request *req,struct reply *reply)
static unsigned get_error(void){return error;}
static void set_error(unsigned value){error=value;}
static void set_win32_error(unsigned value){error=value;}
static user_handle_t get_user_full_handle(user_handle_t win){return valid_window?win:0;}
static struct thread *get_window_thread(user_handle_t win){assert(win);return &target;}
static void release_object(struct thread *thread){assert(thread==&target);released++;}
static struct msg_queue *get_current_queue(void){if(!current->queue)error=queue_error;return current->queue;}
static struct timer *find_timer(struct msg_queue *q,user_handle_t win,unsigned msg,lparam_t id){
    assert(q&&msg==0x113);(void)win;(void)id;lookups++;
    return existing||exhausted?&stored:NULL;
}
static void free_timer(struct msg_queue *q,struct timer *timer){assert(q&&timer==&stored);freed++;existing=0;}
static struct timer *set_timer(struct msg_queue *q,unsigned rate){
    assert(q&&rate==10);allocations++;
    if(allocation_fails){set_error(STATUS_NO_MEMORY);return NULL;}
    return &stored;
}
/* PRODUCTION_TIMER_HANDLER */
static void reset(void){
    memset(&request,0,sizeof(request));memset(&reply,0,sizeof(reply));memset(&stored,0,sizeof(stored));
    error=queue_error=0;lookups=allocations=freed=released=existing=exhausted=allocation_fails=0;valid_window=1;
    queue.next_timer_id=0x7fff;caller=(struct thread){&caller,&queue,0x68,0};target=(struct thread){&caller,&queue,0x70,1};
    request.msg=0x113;request.rate=10;request.lparam=0x1234;
}
int main(void){
    reset();caller.queue=NULL;queue_error=STATUS_ACCESS_DENIED;
    set_win_timer(&request,&reply);
    assert(error==STATUS_ACCESS_DENIED&&!reply.id&&!lookups&&!allocations);
    reset();caller.queue=NULL;
    set_win_timer(&request,&reply);
    assert(error==STATUS_NO_MEMORY&&!reply.id&&!lookups&&!allocations);
    reset();request.win=0x20;target.queue=NULL;
    set_win_timer(&request,&reply);
    assert(error==STATUS_INVALID_HANDLE&&released==1&&!lookups&&!allocations);
    reset();request.win=0x20;target.process=&target;
    set_win_timer(&request,&reply);
    assert(error==STATUS_ACCESS_DENIED&&released==1&&!allocations);
    reset();request.win=0x20;valid_window=0;
    set_win_timer(&request,&reply);
    assert(error==STATUS_INVALID_HANDLE&&!released&&!allocations);
    reset();set_win_timer(&request,&reply);
    assert(!error&&reply.id==0x7fff&&stored.msg==0x113&&stored.lparam==0x1234&&allocations==1);
    reset();request.id=555;existing=1;set_win_timer(&request,&reply);
    assert(!error&&reply.id==555&&freed==1&&allocations==1);
    reset();request.win=0x20;request.id=777;set_win_timer(&request,&reply);
    assert(!error&&reply.id==777&&stored.win==0x20&&released==1&&allocations==1);
    reset();allocation_fails=1;set_win_timer(&request,&reply);
    assert(error==STATUS_NO_MEMORY&&!reply.id);
    reset();exhausted=1;set_win_timer(&request,&reply);
    assert(error==ERROR_NO_MORE_USER_HANDLES&&!reply.id&&!allocations);
    puts("PASS: production window timer request handles missing queues, retained errors, window ownership, allocation failure, ID reuse and exhaustion without a host crash");
}
'''.replace('/* PRODUCTION_TIMER_HANDLER */', handler)
with tempfile.TemporaryDirectory(prefix='mdeck-win-timer-') as tmp:
    folder = Path(tmp)
    file, binary = folder / 'timer.c', folder / 'timer'
    file.write_text(fixture)
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(file), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('No real Steam, Wine session or IPA build.')
