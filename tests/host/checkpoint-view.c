/* Mac fixture for the WoW view registry. The NT map calls below use real
 * MAP_SHARED mappings. Run save and resume as separate host processes. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <sys/mman.h>
#include <unistd.h>

typedef size_t SIZE_T;
typedef unsigned char BYTE;
typedef struct { int64_t QuadPart; } LARGE_INTEGER;
typedef struct { void *Peb; struct { uint32_t UniqueProcess; } ClientId; } TEB;
enum { STATUS_SUCCESS, STATUS_NOT_SUPPORTED, STATUS_INVALID_PARAMETER, STATUS_CONFLICTING_ADDRESSES,
       VPROT_READ = 1, VPROT_WRITE = 2, VPROT_COMMITTED = 32, SEC_COMMIT = 0x8000000,
       PAGE_READONLY = 2, PAGE_READWRITE = 4, IOS_VIEW_SHARED_SECTION = 32, ViewUnmap = 2 };
#define NtCurrentProcess() ((void *)-1)
#define HandleToULong(x) (x)
#define server_enter_uninterrupted_section(m,s) ((void)(s))
#define server_leave_uninterrupted_section(m,s) ((void)(s))
static TEB teb;
static TEB *NtCurrentTeb(void) { return &teb; }
static struct file_view {void *base; size_t size; unsigned int ios_flags, protect;} views[2];
static const size_t granularity_mask = 65535;
static size_t host_page_mask;
static unsigned index_for_pid(void) { return teb.ClientId.UniqueProcess == 12 ? 0 : 1; }
static uintptr_t ios_wow_base_for_peb(void *p) { return (uintptr_t)p; }
static struct file_view *find_view(void *addr, size_t size)
{
    for (unsigned i = 0; i < 2; ++i)
        if (views[i].base == addr && views[i].size == size) return &views[i];
    return NULL;
}
static size_t get_vprot_range_size(void *p, size_t size, BYTE mask, BYTE *out)
{
    *out = (BYTE)find_view(p, size)->protect;
    return size;
}
static unsigned NtMapViewOfSection(void *handle, void *process, void **addr, int bits, int commit,
                                   LARGE_INTEGER *offset, size_t *size, int inherit, int type, unsigned prot)
{
    struct file_view *v = &views[index_for_pid()];
    if (v->base) return STATUS_CONFLICTING_ADDRESSES;
    int writing = prot == PAGE_READWRITE;
    void *p = mmap(*addr, *size, PROT_READ | (writing ? PROT_WRITE : 0), MAP_SHARED | MAP_FIXED,
                   fileno(handle), offset->QuadPart);
    if (p == MAP_FAILED) return STATUS_NOT_SUPPORTED;
    *addr = p;
    *v = (struct file_view){p, *size, IOS_VIEW_SHARED_SECTION,
                           SEC_COMMIT | VPROT_COMMITTED | VPROT_READ | (writing ? VPROT_WRITE : 0)};
    return 0;
}
static void NtUnmapViewOfSection(void *process, void *addr)
{
    struct file_view *v = &views[index_for_pid()];
    assert(v->base == addr && !munmap(addr, v->size));
    *v = (struct file_view){0};
}
#include "../../build/ntdll-unix/checkpoint_view.inc"
#include "../../build/wineserver/checkpoint_section.h"
#include <fcntl.h>

int main(int argc, char **argv)
{
    assert(argc == 3 && !chdir(argv[2]));
    const int saving = !strcmp(argv[1], "save");
    const uint64_t backing = 17;
    const size_t unit = 65536, bytes = unit * 2;
    host_page_mask = getpagesize() - 1;
    int dir = open(".", O_RDONLY | O_DIRECTORY);
    FILE *file = tmpfile(), *metadata = fopen("views", saving ? "wb" : "rb");
    assert(dir >= 0 && file && metadata && !ftruncate(fileno(file), bytes));
    if (!saving) assert(!madeira_load_section_bytes(dir, backing, fileno(file), bytes));
    char *reserve = mmap(NULL, unit * 12, PROT_NONE, MAP_ANON | MAP_PRIVATE, -1, 0);
    assert(reserve != MAP_FAILED);
    uintptr_t base = ((uintptr_t)reserve + unit - 1) & ~(uintptr_t)(unit - 1);
    for (unsigned i = 0; i < 2; ++i)
    {
        teb.ClientId.UniqueProcess = 12 + 4 * i;
        teb.Peb = (void *)(base + i * unit * 6);
        struct ios_checkpoint_view record;
        if (saving)
        {
            void *addr = (char *)teb.Peb + (i + 1) * unit;
            size_t size = i ? unit : bytes;
            unsigned prot = i ? PAGE_READONLY : PAGE_READWRITE;
            LARGE_INTEGER off = {.QuadPart = i * unit};
            assert(!NtMapViewOfSection(file, NULL, &addr, 0, 0, &off, &size, ViewUnmap, 0, prot));
            assert(!ios_checkpoint_describe_view(teb.ClientId.UniqueProcess, (uintptr_t)teb.Peb,
                   (uintptr_t)addr, size, off.QuadPart, backing, &record));
            assert(record.guest_base == (i + 1) * unit && record.offset == i * unit && record.protection == prot);
            assert(fwrite(&record, sizeof(record), 1, metadata) == 1);
        }
        else
        {
            assert(fread(&record, sizeof(record), 1, metadata) == 1);
            ++teb.ClientId.UniqueProcess;
            assert(ios_checkpoint_attach_view(&record, file) == STATUS_INVALID_PARAMETER);
            --teb.ClientId.UniqueProcess;
            assert(!ios_checkpoint_attach_view(&record, file));
            assert(ios_checkpoint_attach_view(&record, file) == STATUS_CONFLICTING_ADDRESSES);
        }
    }
    int *writer = (int *)((char *)views[0].base + unit), *reader = views[1].base;
    if (saving)
    {
        *writer = 7;
        assert(*reader == 7 && !madeira_save_section_bytes(dir, backing, fileno(file), bytes));
    }
    else
    {
        assert(*reader == 7 && ++*writer == 8 && *reader == 8);
        puts("PASS restored two guest views, distinct addresses, shared offset and retained protections");
    }
    assert(!fclose(metadata));
    return 0;
}
