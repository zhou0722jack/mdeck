#!/usr/bin/env python3
"""Run production debug-channel selection and native fault guards; no Wine or device run."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
bridge = (ROOT / 'app/Madeira/WineProcessBridge.m').read_text()
server = (ROOT / 'app/Madeira/WineServerBridge.m').read_text()
signal = (ROOT / 'build/ntdll-unix/signal_arm64_ios.c').read_text()


def function(source, name):
    start = source.index(name)
    brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


start = function(server, 'int wineserver_start(')
assert start.index('madeira_configure_wine_debug();') < start.index('madeira_seed_prefix_if_needed(prefix_path)') < start.index('pthread_create(')
assert 'madeira_configure_wine_debug();' in function(bridge, 'static void *wine_process_thread(')
assert 'setenv("WINEDEBUG"' not in bridge
print('PASS: debug channels are selected before wineserver startup and the guest, using one implementation')

guard = function(signal, 'static BOOL handle_syscall_fault(')
native_test = r'''
#include <assert.h>
#include <stdint.h>
#include <setjmp.h>
#include <stdio.h>
#define TRUE 1
#define FALSE 0
#define TRACE(...) ((void)0)
typedef int BOOL;
typedef unsigned int DWORD;
typedef uintptr_t ULONG_PTR;
typedef uint64_t DWORD64;
typedef struct { uintptr_t pc, sp, regs[32]; } ucontext_t;
typedef struct { unsigned ExceptionCode, ExceptionFlags, NumberParameters; void *ExceptionAddress; uintptr_t ExceptionInformation[15]; } EXCEPTION_RECORD;
struct syscall_frame { uintptr_t pc; };
struct thread_data { void *jmp_buf; };
static struct syscall_frame frame;
static struct thread_data data;
static int has_teb, has_frame, inside, frame_reads, inside_reads, data_reads;
static void *NtCurrentTeb(void) { return has_teb ? (void *)0x100000000ULL : NULL; }
static struct syscall_frame *get_syscall_frame(void) {
    assert(has_teb); frame_reads++; return has_frame ? &frame : NULL;
}
static int is_inside_syscall(uintptr_t sp) { (void)sp; assert(has_teb && has_frame); inside_reads++; return inside; }
static struct thread_data *ntdll_get_thread_data(void) { assert(has_teb); data_reads++; return &data; }
static unsigned GetCurrentThreadId(void) { return 24; }
static void __wine_syscall_dispatcher_return(void) {}
#define SP_sig(c) ((c)->sp)
#define PC_sig(c) ((c)->pc)
#define REGn_sig(n,c) ((c)->regs[n])
''' + guard + r'''
int main(void) {
    ucontext_t context = {.pc=0x1234, .sp=0x5678};
    EXCEPTION_RECORD record = {.ExceptionCode=0xc0000005};
    assert(!handle_syscall_fault(&context,&record));
    assert(!frame_reads && !inside_reads && !data_reads && context.pc==0x1234);
    has_teb=1;
    assert(!handle_syscall_fault(&context,&record));
    assert(frame_reads==1 && !inside_reads && !data_reads);
    has_frame=1;
    assert(!handle_syscall_fault(&context,&record));
    assert(inside_reads==1 && !data_reads && context.pc==0x1234);
    inside=1; data.jmp_buf=(void *)0xabcdef00;
    assert(handle_syscall_fault(&context,&record));
    assert(context.regs[0]==0xabcdef00 && context.regs[1]==1 && !data.jmp_buf);
    assert(context.pc==(uintptr_t)longjmp);
    assert(handle_syscall_fault(&context,&record));
    assert(context.regs[0]==0xc0000005 && context.regs[18]==(uintptr_t)NtCurrentTeb());
    assert(context.sp==(uintptr_t)&frame && context.pc==(uintptr_t)__wine_syscall_dispatcher_return);
    puts("PASS: no-TEB/no-frame/native faults decline safely; Wine exception and syscall-return paths remain intact");
}
'''

with tempfile.TemporaryDirectory(prefix='mdeck-wine-diagnostic-') as directory:
    directory = Path(directory)
    source = directory / 'channels.c'
    source.write_text('#include "madeira_debug.h"\nint madeira_get_diag_enabled(void) { const char *v=getenv("TEST_EXTENDED"); return v && *v==\'1\'; }\nint main(void) { madeira_configure_wine_debug(); puts(getenv("WINEDEBUG")); }\n')
    executable = directory / 'channels'
    cc = os.environ.get('CC', 'cc')
    subprocess.run([cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-I', str(ROOT / 'build'), str(source), '-o', str(executable)], check=True)
    docs = directory / 'Documents'
    docs.mkdir()
    cfg = docs / 'madeira.cfg'
    game = directory / 'game.cfg'
    env = dict(os.environ, MADEIRA_DOCS_DIR=str(docs), HOME=str(directory))
    for key in ['MADEIRA_DEBUG_VERBOSE', 'MADEIRA_CFG_GAME', 'WINEDEBUG', 'MADEIRA_CFG_EARLY_DOCS', 'MADEIRA_CONTAINER_HOME']:
        env.pop(key, None)

    def channels(global_text='', game_text=None, verbose=None, extended=False):
        cfg.write_text(global_text)
        case = dict(env)
        if game_text is not None:
            game.write_text(game_text)
            case['MADEIRA_CFG_GAME'] = str(game)
        if verbose is not None:
            case['MADEIRA_DEBUG_VERBOSE'] = verbose
        case['TEST_EXTENDED'] = '1' if extended else '0'
        result = subprocess.run([str(executable)], env=case, text=True, capture_output=True, check=True)
        assert ('[wine-debug]' in result.stderr) == extended
        return result.stdout.strip()

    assert channels() == 'err+all,err-virtual,fixme-d3dcompiler'
    value = channels('env.MADEIRA_DEBUG_VERBOSE = 1\n')
    assert 'trace+module' in value and 'trace+msvcrt' not in value and 'trace+nls' not in value
    assert 'trace+msvcrt' not in channels(verbose='1')
    value = channels(extended=True)
    assert 'trace+msvcrt' in value and 'trace+nls' in value
    assert channels('env.MADEIRA_DEBUG_VERBOSE = 0\n', verbose='1') == channels()
    assert channels('env.MADEIRA_DEBUG_VERBOSE = 1\n', 'env.MADEIRA_DEBUG_VERBOSE = 0\n') == channels()
    assert channels('env.MADEIRA_DEBUG_VERBOSE = 1\nenv.WINEDEBUG = trace+nls\n') == 'trace+nls'
    assert channels('env.WINEDEBUG = trace+nls\n', 'env.WINEDEBUG = trace+msvcrt\n') == 'trace+msvcrt'
    assert channels('env.WINEDEBUG = err+all\n', extended=True) == 'err+all,trace+msvcrt,trace+nls'
    print('PASS: configured verbose flag is effective before env export; global/game overrides and explicit WINEDEBUG are preserved')

    source = directory / 'fault.c'
    source.write_text(native_test)
    executable = directory / 'fault'
    subprocess.run([cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-fsanitize=address,undefined', str(source), '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
print('Host tests only; Steam installation and device behavior remain unverified.')
