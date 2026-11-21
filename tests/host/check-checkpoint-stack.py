"""Exercise the production WoW stack copier with real Mach page protection."""
from pathlib import Path
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
source = (root / 'build/ntdll-unix/virtual_ios.c').read_text()
start = source.index('static NTSTATUS checkpoint_stack_layout(')
end = source.index('static const WCHAR shared_data_nameW', start)
harness = r'''
#include <assert.h>
#include <mach/mach.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
typedef int NTSTATUS, BOOL, INITIAL_TEB;
typedef uintptr_t ULONG_PTR, SIZE_T;
typedef unsigned char BYTE;
typedef struct { uint32_t DeallocationStack, GuaranteedStackBytes; struct { uint32_t StackLimit, StackBase; } Tib; } WOW_TEB;
typedef struct { WOW_TEB wow; void *Peb; struct { uint32_t UniqueProcess, UniqueThread; } ClientId; } TEB;
#include "checkpoint_stack.h"
#define TRUE 1
#define FALSE 0
#define STATUS_SUCCESS 0
#define STATUS_INVALID_PARAMETER 1
#define STATUS_NOT_SUPPORTED 2
#define STATUS_BUFFER_TOO_SMALL 3
#define STATUS_ACCESS_DENIED 4
#define HandleToULong(x) (x)
#define VPROT_READ 1
#define VPROT_WRITE 2
#define VPROT_COMMITTED 32
#define VPROT_GUARD 16
#define IOS_VIEW_GUEST_STACK 16
#define get_wow_teb(t) (&(t)->wow)
#define server_enter_uninterrupted_section(m,s) ((void)0)
#define server_leave_uninterrupted_section(m,s) ((void)0)
#define host_page_size test_page_size
static size_t host_page_size;
static struct ios_wow_window { uintptr_t base; } window;
static struct file_view { char *base; size_t size; unsigned ios_flags; } view;
static struct ios_wow_window *ios_wow_slot_for_peb(void *p) { return p == &window ? &window : NULL; }
static struct ios_wow_window *ios_wow_live_slot_for_addr(void *teb) { return &window; }
static struct file_view *find_view(char *addr, size_t len) { return &view; }
static size_t get_vprot_range_size(char *p, size_t size, BYTE mask, BYTE *out)
{
    if (p == view.base) { *out = 0; return host_page_size; }
    if (p == view.base + host_page_size) { *out = 51; return host_page_size; }
    *out = 35;
    return size;
}
'''
fixture = r'''
int main(int argc, char **argv)
{
    assert(argc == 3);
    int save = !strcmp(argv[1], "save");
    host_page_size = getpagesize();
    size_t n = host_page_size * 5, payload_size = n - host_page_size;
    uint32_t low = 0x200000;
    vm_address_t host = 0, saved_host = 0;
    FILE *f = fopen(argv[2], save ? "wb" : "rb");
    assert(f && vm_allocate(mach_task_self(), &host, 2 * n, VM_FLAGS_ANYWHERE) == KERN_SUCCESS);
    if (save) assert(fwrite(&host, sizeof(host), 1, f) == 1);
    else
    {
        assert(fread(&saved_host, sizeof(saved_host), 1, f) == 1);
        if (host == saved_host) host += n;
        assert(host != saved_host);
    }
    window.base = host - low;
    view = (struct file_view){(char *)host, n, IOS_VIEW_GUEST_STACK};
    char *p = view.base;
    TEB teb = { .Peb = &window, .ClientId = {12, 16} };
    teb.wow.DeallocationStack = low;
    teb.wow.Tib.StackBase = low + n;
    teb.wow.Tib.StackLimit = low + 2 * host_page_size;
    teb.wow.GuaranteedStackBytes = save ? 32768 : 0;
    if (save) for (size_t i = host_page_size; i < n; ++i) p[i] = (char)(1 + i % 117);
    assert(!mprotect(p, 2 * host_page_size, PROT_NONE));
    void *buf = malloc(payload_size);
    struct ios_checkpoint_stack record;
    assert(ios_checkpoint_capture_stack(&teb, &record, NULL, 0) == STATUS_BUFFER_TOO_SMALL);
    assert(buf);
    if (save)
    {
        view.ios_flags = 0;
        assert(ios_checkpoint_capture_stack(&teb, &record, buf, payload_size) == STATUS_NOT_SUPPORTED);
        view.ios_flags = IOS_VIEW_GUEST_STACK;
        assert(!ios_checkpoint_capture_stack(&teb, &record, buf, payload_size));
        assert(fwrite(&record, sizeof(record), 1, f) == 1 && fwrite(buf, payload_size, 1, f) == 1);
    }
    else
    {
        assert(fread(&record, sizeof(record), 1, f) == 1 && fread(buf, payload_size, 1, f) == 1);
        record.tid++;
        assert(ios_checkpoint_restore_stack(&teb, &record, buf, payload_size) == STATUS_INVALID_PARAMETER);
        record.tid--;
        assert(ios_checkpoint_restore_stack(&teb, &record, buf, payload_size - 1) == STATUS_INVALID_PARAMETER);
        assert(!ios_checkpoint_restore_stack(&teb, &record, buf, payload_size));
        assert(teb.wow.GuaranteedStackBytes == 32768);
    }
    assert(!fclose(f));
    vm_size_t copied = 0;
    assert(vm_read_overwrite(mach_task_self(), host + host_page_size, 1, (vm_address_t)buf, &copied) != KERN_SUCCESS);
    assert(!mprotect(p + host_page_size, host_page_size, PROT_READ));
    for (size_t i = host_page_size; i < n; ++i) assert(p[i] == (char)(1 + i % 117));
}
'''
with tempfile.TemporaryDirectory() as temp:
    exe = Path(temp) / 'stack'
    state = Path(temp) / 'state'
    subprocess.run(['clang', '-O2', '-I', str(root / 'build/ntdll-unix'), '-x', 'c',
                    '-', '-o', str(exe)], input=harness + source[start:end] + fixture, text=True, check=True)
    for mode in ('save', 'restore'):
        subprocess.run([exe, mode, state], check=True)
print('PASS fresh-process WoW stack at a different host base, same guest addresses, guard bytes and protections')
