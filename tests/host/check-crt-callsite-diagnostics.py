#!/usr/bin/env python3
"""Compile the runtime patch's diagnostics and parameter checks with controlled handlers."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
wine_root = Path(subprocess.check_output(['git', '-C', str(ROOT / 'wine'), 'rev-parse', '--show-toplevel'], text=True).strip())
assert wine_root == ROOT / 'wine', 'Initialize the pinned Wine submodule before running this check'
assert subprocess.check_output(['git', '-C', str(wine_root), 'rev-parse', 'HEAD'], text=True).strip() == subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD:wine'], text=True).strip()
patch = ROOT / 'build/windows-runtime/patches/0001-crt-invalid-parameter-callsite.patch'
lines = patch.read_text().splitlines(keepends=True)
sources = {}
i = 0
while i < len(lines):
    if not lines[i].startswith('--- a/'):
        i += 1
        continue
    name = lines[i][6:].strip()
    original = subprocess.check_output(['git', '-C', str(ROOT / 'wine'), 'show', 'HEAD:' + name], text=True).splitlines(keepends=True)
    i += 2
    result, cursor = [], 0
    while i < len(lines) and lines[i].startswith('@@'):
        match = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', lines[i])
        start = int(match[1]) - 1
        result += original[cursor:start]
        cursor = start
        i += 1
        while i < len(lines) and lines[i][:1] in [' ', '+', '-'] and not lines[i].startswith('--- '):
            line = lines[i]
            if line[0] in ' -':
                assert original[cursor] == line[1:], (name, cursor)
                cursor += 1
            if line[0] in ' +':
                result.append(line[1:])
            i += 1
    result += original[cursor:]
    sources[name] = ''.join(result)

assert set(sources) == {'dlls/msvcrt/msvcrt.h', 'dlls/msvcrt/errno.c', 'dlls/ntdll/unix/debug.c'}
subprocess.run(['git', '-C', str(ROOT / 'wine'), 'apply', '--check', str(patch)], check=True)


def function(source, name):
    start = source.index(name)
    brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


header = sources['dlls/msvcrt/msvcrt.h']
checks = header[header.index('static inline void msvcrt_trace_invalid_parameter('):header.index('typedef int (*puts_clbk_a)')]
errno = sources['dlls/msvcrt/errno.c']
entries = '\n'.join(function(errno, signature) for signature in [
    'void __cdecl _invalid_parameter(', 'void CDECL _invalid_parameter_noinfo(', 'void CDECL _invalid_parameter_noinfo_noreturn('])
flags = function(sources['dlls/ntdll/unix/debug.c'], 'unsigned char __cdecl __wine_dbg_get_channel_flags(')
program = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stddef.h>
#include <wchar.h>
#include <stdarg.h>
#include <errno.h>
#define __cdecl
#define CDECL
#define WINE_IOS 1
#define _MSVCR_VER 140
#define TRUE 1
#define FALSE 0
#define EXCEPTION_NONCONTINUABLE 1
#define STATUS_INVALID_CRUNTIME_PARAMETER 0xc0000417U
enum { __WINE_DBCL_ERR=1, __WINE_DBCL_TRACE=3, __WINE_DBCL_INIT=7 };
struct __wine_debug_channel { unsigned char flags; char name[16]; };
static int extended, nb_debug_options=0, default_flags=2;
static struct __wine_debug_channel debug_options[1];
static void init_options(void) { nb_debug_options=0; }
static int madeira_get_diag_enabled(void) { return extended; }
''' + flags + r'''
static int value_errno, detailed, errors, raised, exits, global_calls, thread_calls;
static char last_detail[2048];
static int *_errno(void) { return &value_errno; }
static void detailed_log(const char *format, ...) {
    va_list args; va_start(args,format);
    vsnprintf(last_detail,sizeof(last_detail),format,args); va_end(args);
    detailed++; value_errno=999;
}
#define WINE_DECLARE_DEBUG_CHANNEL(ch) static struct __wine_debug_channel __wine_dbch_##ch={255,#ch}
#define TRACE_ON(ch) (__wine_dbg_get_channel_flags(&__wine_dbch_##ch) & (1<<__WINE_DBCL_TRACE))
#define TRACE_(ch) if (__wine_dbg_get_channel_flags(&__wine_dbch_##ch) & (1<<__WINE_DBCL_TRACE)) detailed_log
#define ERR(...) ((void)(errors++))
#define debugstr_w(p) (p)
typedef void (*handler)(const wchar_t*,const wchar_t*,const wchar_t*,unsigned int,uintptr_t);
typedef struct { handler invalid_parameter_handler; } thread_data_t;
static thread_data_t thread_data;
static handler invalid_parameter_handler;
static thread_data_t *msvcrt_get_thread_data(void) { return &thread_data; }
static void RaiseException(unsigned int code,unsigned int flags,unsigned int count,const void *args) {
    assert(code==STATUS_INVALID_CRUNTIME_PARAMETER && flags==1 && !count && !args); raised++;
}
static void test_exit(unsigned int code) { assert(code==STATUS_INVALID_CRUNTIME_PARAMETER); exits++; }
#define _exit test_exit
''' + checks + entries + r'''
static void global_handler(const wchar_t *a,const wchar_t *b,const wchar_t *c,unsigned int line,uintptr_t arg) {
    assert(!a && !b && !c && !line && !arg); global_calls++;
}
static void thread_handler(const wchar_t *a,const wchar_t *b,const wchar_t *c,unsigned int line,uintptr_t arg) {
    assert(!a && !b && !c && !line && !arg); thread_calls++;
}
int main(void) {
    int n=0;
    struct __wine_debug_channel channel={0,"madeira_crt"}, ordinary={2,"msvcrt"};
    assert(__wine_dbg_get_channel_flags(&ordinary)==2);
    assert(!(__wine_dbg_get_channel_flags(&channel)&(1<<__WINE_DBCL_TRACE)));
    assert(MSVCRT_CHECK_PMT_ERR(++n==1,ERANGE));
    assert(n==1 && !detailed && !raised && !errors);
    assert(!MSVCRT_CHECK_PMT_ERR(++n==1,ERANGE));
    assert(n==2 && !detailed && raised==1 && errors==1 && value_errno==ERANGE);
    extended=1;
    assert(__wine_dbg_get_channel_flags(&channel)&(1<<__WINE_DBCL_TRACE));
    invalid_parameter_handler=global_handler;
    assert(!MSVCRT_CHECK_PMT_ERR(++n==1,ERANGE));
    assert(n==3 && global_calls==1 && raised==1 && detailed==1 && value_errno==ERANGE);
    assert(strstr(last_detail,"++n==1") && strstr(last_detail,"function=main") && strstr(last_detail,"caller="));
    thread_data.invalid_parameter_handler=thread_handler;
    assert(!MSVCRT_CHECK_PMT(0));
    assert(thread_calls==1 && global_calls==1 && raised==1 && value_errno==EINVAL);
    extended=0;
    int before=detailed;
    assert(!(__wine_dbg_get_channel_flags(&channel)&(1<<__WINE_DBCL_TRACE)));
    assert(!MSVCRT_CHECK_PMT(0));
    assert(detailed==before && thread_calls==2 && value_errno==EINVAL);
    thread_data.invalid_parameter_handler=NULL; invalid_parameter_handler=NULL;
    _invalid_parameter_noinfo();
    assert(detailed==before && raised==2 && errors==2);
    _invalid_parameter_noinfo_noreturn();
    assert(detailed==before && raised==3 && exits==1);
    extended=1;
    before=detailed;
    value_errno=17;
    _invalid_parameter_noinfo();
    assert(detailed==before+2 && raised==4 && errors==4);
    assert(value_errno==17);
    assert(strstr(last_detail,"function=_invalid_parameter"));
    puts("PASS: success is silent; failed checks retain expression, errno and handler arguments");
    puts("PASS: thread/global handler precedence, fatal status and noreturn exit are unchanged");
    puts("PASS: extended logging gates detailed output live, including on/off changes after channel initialization");
}
'''
with tempfile.TemporaryDirectory(prefix='mdeck-crt-diagnostic-') as directory:
    folder = Path(directory)
    source = folder / 'check.c'
    source.write_text(program)
    binary = folder / 'check'
    subprocess.run([os.environ.get('CC','cc'), '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                    '-Wno-unused-parameter', '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('PASS: diagnostic patch matches the pinned Wine source; no runtime error is suppressed')
