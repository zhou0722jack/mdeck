/* Execute the original DLL's scalar/SSE4.1/AVX2 scanner bodies on macOS x86_64.
 * The PE loader and PCScan mark callback are fixtures. The scanner instructions
 * and mask constants come from the supplied memory-mapped DLL image. */
#include <assert.h>
#include <cpuid.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

static uint64_t visited[64];
static size_t visited_count;

__attribute__((ms_abi)) static uint64_t mark(void *context, uint64_t pointer)
{
    (void)context;
    assert(visited_count < 64);
    visited[visited_count++] = pointer;
    return 0;
}

typedef void (__attribute__((ms_abi)) *scanner)(void *, uint64_t *, uint64_t *);

int main(int argc, char **argv)
{
    assert(argc == 3 || argc == 6);
    size_t scanner_rva = argc == 6 ? strtoull(argv[3], NULL, 0) : 0xe4030;
    size_t mark_rva = argc == 6 ? strtoull(argv[4], NULL, 0) : 0xe5f70;
    size_t regular_slot_rva = argc == 6 ? strtoull(argv[5], NULL, 0) : 0x13ae80;
    unsigned int eax, ebx, ecx, edx;
    assert(__get_cpuid(1, &eax, &ebx, &ecx, &edx));
    assert(ecx & bit_SSE4_1);
    assert(__get_cpuid_count(7, 0, &eax, &ebx, &ecx, &edx));
    int avx2_available = (ebx & bit_AVX2) != 0;
    FILE *file = fopen(argv[1], "rb");
    assert(file);
    assert(fseek(file, 0, SEEK_END) == 0);
    size_t length = (size_t)ftell(file);
    rewind(file);
    size_t allocation = (length + 4095) & ~(size_t)4095;
    unsigned char *image = mmap(NULL, allocation, PROT_READ | PROT_WRITE,
                                MAP_ANON | MAP_PRIVATE, -1, 0);
    assert(image != MAP_FAILED);
    assert(fread(image, 1, length, file) == length);
    fclose(file);
    /* The actual scanner calls the complex mark/metadata routine. Substitute
     * only that callback to observe candidate selection without a CEF heap. */
    unsigned char jump[12] = {0x48, 0xb8};
    uint64_t callback = (uint64_t)(uintptr_t)mark;
    memcpy(jump + 2, &callback, sizeof(callback));
    jump[10] = 0xff;
    jump[11] = 0xe0;
    assert(mark_rva + sizeof(jump) <= length);
    assert(scanner_rva < length && regular_slot_rva + sizeof(uint64_t) <= length);
    memcpy(image + mark_rva, jump, sizeof(jump));
    assert(mprotect(image, allocation, PROT_READ | PROT_WRITE | PROT_EXEC) == 0);
    uint64_t pool_bytes = strtoull(argv[2], NULL, 10);
    uint64_t *values;
    assert(posix_memalign((void **)&values, 32, 32 * sizeof(*values)) == 0);
    size_t cases = 0;
    for (size_t placement = 0; placement < 4; ++placement) {
        uint64_t base = UINT64_C(0x1000000000) + placement * pool_bytes;
        memcpy(image + regular_slot_rva, &base, sizeof(base));
        for (size_t count = 0; count <= 31; ++count) {
            for (size_t index = 0; index < count; ++index) {
                uint64_t candidates[] = {0, base - 1, base, base + 1,
                    base + pool_bytes - 1, base + pool_bytes,
                    base + pool_bytes + 0x200000, base + pool_bytes * 2};
                values[index] = candidates[index % 8];
            }
            for (unsigned int type = 0; type < (avx2_available ? 3u : 2u); ++type) {
                visited_count = 0;
                unsigned char context[32] = {0};
                context[0] = type;
                ((scanner)(void *)(image + scanner_rva))(context, values, values + count);
                size_t expected = 0;
                for (size_t index = 0; index < count; ++index) {
                    if (values[index] >= base && values[index] - base < pool_bytes) {
                        assert(expected < visited_count);
                        assert(visited[expected++] == values[index]);
                    }
                }
                assert(visited_count == expected);
                ++cases;
            }
        }
    }
    printf("PASS native scalar/SSE4.1%s DLL scanner bodies, %zu cases, pool=%llu%s\n",
           avx2_available ? "/AVX2" : "", cases, (unsigned long long)pool_bytes,
           avx2_available ? "" : "; native AVX2 unavailable");
    free(values);
    assert(munmap(image, allocation) == 0);
    return 0;
}
