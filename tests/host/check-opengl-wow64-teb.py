#!/usr/bin/env python3
"""Exercise the patched OpenGL TEB conversion with real high-address storage."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
patch = ROOT / 'build/windows-runtime/patches/0002-opengl-wow64-teb-host-pointer.patch'
subprocess.run(['git', '-C', str(ROOT / 'wine'), 'apply', '--check', str(patch)], check=True)
source = subprocess.check_output(['git', '-C', str(ROOT / 'wine'), 'show',
                                  'HEAD:dlls/opengl32/unix_private.h'], text=True)
lines = source.splitlines(keepends=True)
result, cursor = [], 0
diff = patch.read_text().splitlines(keepends=True)
i = 2
while i < len(diff):
    match = re.match(r'@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@', diff[i])
    assert match
    start = int(match[1]) - 1
    result += lines[cursor:start]
    cursor = start
    i += 1
    while i < len(diff) and not diff[i].startswith('@@'):
        line = diff[i]
        if line[0] in ' -':
            assert lines[cursor] == line[1:]
            cursor += 1
        if line[0] in ' +':
            result.append(line[1:])
        i += 1
result += lines[cursor:]
patched = ''.join(result)

def function(text, signature):
    start = text.index(signature)
    end = text.index('\n}', start) + 2
    return text[start:end]

helper = function(patched, 'static inline TEB *get_teb64(')
old = function(source, 'static inline TEB *get_teb64(').replace('get_teb64(', 'old_get_teb64(')
wgl = (ROOT / 'wine/dlls/opengl32/unix_wgl.c').read_text()
attach = function(wgl, 'NTSTATUS thread_attach(')
wow = function(wgl, 'NTSTATUS wow64_thread_attach(')
assert '/* 0fdc */' in (ROOT / 'wine/include/winternl.h').read_text()

program = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <assert.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>
#include <stdio.h>
typedef uint32_t ULONG;
typedef uintptr_t ULONG_PTR;
typedef int NTSTATUS;
#define STATUS_SUCCESS 0
#define ULongToPtr(p) ((void *)(uintptr_t)(ULONG)(p))
typedef struct { void *glTable; } TEB;
typedef struct { unsigned char reserved[0xfdc]; int32_t WowTebOffset; } TEB32;
_Static_assert(offsetof(TEB32,WowTebOffset)==0xfdc,"offset from the device fault");
static uintptr_t window;
static int null_opengl_funcs;
static void *ios_wow_host_ptr(ULONG p) { return p ? (void *)(window+p) : NULL; }
''' + helper + '\n' + attach + '\n' + wow + '\n' + old + r'''
int main(void) {
    struct rlimit limit={0,0};setrlimit(RLIMIT_CORE,&limit);
    unsigned char *storage=mmap(NULL,0x10000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);
    assert(storage!=MAP_FAILED && (uintptr_t)storage>UINT32_MAX);
    TEB *teb64=(TEB *)(storage+0x2000);
    TEB32 *teb32=(TEB32 *)(storage+0x4000);
    teb32->WowTebOffset=-0x2000;
    window=(uintptr_t)teb32-0x302000;
#ifdef WINE_IOS
    assert(get_teb64((uintptr_t)teb32)==teb64); /* already-relocated outer args */
    assert(get_teb64(0x302000)==teb64);         /* embedded guest PTR32 */
    assert(wow64_thread_attach(teb32)==0 && teb64->glTable==&null_opengl_funcs);
    teb32->WowTebOffset=0x2000;
    assert(get_teb64(0x302000)==(TEB *)((char *)teb32+0x2000));
    teb32->WowTebOffset=-0x2000;
    pid_t child=fork();assert(child>=0);
    if(!child) { volatile TEB *p=old_get_teb64((ULONG)(uintptr_t)teb32);(void)p;_exit(0); }
    int status=0;assert(waitpid(child,&status,0)==child && WIFSIGNALED(status));
    puts("PASS: real high-host and embedded guest TEB pointers resolve once; signed offsets and thread_attach work; old code faults");
#else
    /* Without iOS relocation the helper retains the original zero-extension. */
    (void)teb64;(void)ios_wow_host_ptr;(void)old_get_teb64;
    puts("PASS: non-iOS helper compiles with unchanged ULongToPtr path");
#endif
    assert(munmap(storage,0x10000)==0);
}
'''
with tempfile.TemporaryDirectory(prefix='mdeck-wgl-teb-') as tmp:
    file = Path(tmp) / 'check.c'
    file.write_text(program)
    for flags in [['-DWINE_IOS=1'], []]:
        binary = Path(tmp) / 'check'
        subprocess.run(['xcrun', 'clang', '-O0', '-Wall', '-Wextra', '-Werror', *flags,
                        str(file), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
print('Host pointer-conversion regression only; no Steam, IPA or physical-device acceptance.')
