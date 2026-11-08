#!/usr/bin/env python3
"""PA126 exact full-size placement, kernel ownership, and image identity checks."""
from pathlib import Path
import argparse
import hashlib
import struct
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
NATIVE=ROOT/'build/ntdll-unix'
parser=argparse.ArgumentParser()
parser.add_argument('--official-image',type=Path)
args=parser.parse_args()
source=(NATIVE/'virtual_ios.c').read_text()
def function(text,signature):
    start=text.index(signature)
    return text[start:text.index('\n}',start)+2]
assert source.index('if (process != NtCurrentProcess())')<source.index('goto steam_cef_allocated;')
assert 'ios_steam_cef_pool_image(getenv(' in source
assert 'ios_steam_cef_reserve_full,NULL,&placed)' in source
assert source.index('steam_cef_allocated:')<source.index('ios_steam_cef_allocation_result(getenv(')
assert 'compile_one "$BUILD_DIR/steam_cef_pools.c" "steam_cef_pools"' in (NATIVE/'build.sh').read_text()
assert 'ios_steam_cef_pool_forget(' in (NATIVE/'process_ios.c').read_text()
mapped=bytearray(0x166000)
if args.official_image:
    binary=args.official_image.read_bytes()
    assert hashlib.sha256(binary).hexdigest()=='6358830f96f36efa7516b3277cf69c1f132f97d4d93c365ccf061a7cf11e1e39'
    pe=struct.unpack_from('<I',binary,0x3c)[0]
    mapped[:0x400]=binary[:0x400]
    section=pe+24+struct.unpack_from('<H',binary,pe+20)[0]
    for i in range(struct.unpack_from('<H',binary,pe+6)[0]):
        at=section+40*i;virtual_size,va,raw_size,raw=struct.unpack_from('<IIII',binary,at+8)
        assert va+raw_size<=len(mapped)
        mapped[va:va+raw_size]=binary[raw:raw+raw_size]
else:
    # Public byte excerpts from the pinned Valve image; enough to test the
    # allowlist gate offline. --official-image additionally checks the whole DLL.
    mapped[:2]=b'MZ';struct.pack_into('<I',mapped,0x3c,0x80)
    mapped[0x80:0x84]=b'PE\0\0';struct.pack_into('<H',mapped,0x84,0x8664)
    struct.pack_into('<I',mapped,0x88,0x66956fee);struct.pack_into('<I',mapped,0xd0,len(mapped))
    mapped[0x4e0aa:0x4e0aa+64]=bytes.fromhex('1000007423488d0d7a171000e885c3020089c6488d0d5c171000ff15666e0c0089f04883c4205ec3488d0d57171000e822f9ffffc6054317100001ebc8488d0d')
    mapped[0xdc0f4:0xdc0f4+32]=bytes.fromhex('488d4c2424c7012f000000e8dcc4f3ffcccc0f0bcccccccccccccccc4883ec28')
with tempfile.TemporaryDirectory(prefix='mdeck-cef-pools-') as temporary:
    folder=Path(temporary);image=folder/'mapped.bin';image.write_bytes(mapped)
    backend=function(source,'static unsigned int ios_steam_cef_reserve_full(')
    adapter=folder/'adapter.c'
    adapter.write_text(r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
typedef uint32_t NTSTATUS;
typedef size_t SIZE_T;
#define MEM_RESERVE 0x2000
#define MEM_RELEASE 0x8000
#define PAGE_NOACCESS 1
#define STATUS_NO_MEMORY 0xc0000017u
#define NtCurrentProcess() ((void *)(intptr_t)-1)
static int mode,freed;
static NTSTATUS allocate_virtual_memory(void **address,SIZE_T *size,unsigned type,unsigned protect,
    uintptr_t low,uintptr_t high,uintptr_t align,unsigned attributes) {
    assert(type==MEM_RESERVE&&protect==PAGE_NOACCESS&&!low&&!high&&!align&&!attributes);
    if(mode==1)return STATUS_NO_MEMORY;
    if(mode==2)*address=(char *)*address+65536;
    if(mode==3)*size-=65536;
    return 0;
}
static NTSTATUS NtFreeVirtualMemory(void *process,void **address,SIZE_T *size,unsigned type) {
    assert(process==NtCurrentProcess()&&*address&&!*size&&type==MEM_RELEASE);freed++;return 0;
}
''' + backend + r'''
int main(void) {
    const uint64_t base=0x7800000000ull,wanted=0x400000000ull;
    assert(!ios_steam_cef_reserve_full(NULL,base,wanted)&&!freed);
    mode=1;assert(ios_steam_cef_reserve_full(NULL,base,wanted)==STATUS_NO_MEMORY&&!freed);
    mode=2;assert(ios_steam_cef_reserve_full(NULL,base,wanted)==STATUS_NO_MEMORY&&freed==1);
    mode=3;assert(ios_steam_cef_reserve_full(NULL,base,wanted)==STATUS_NO_MEMORY&&freed==2);
}
''')
    adapter_binary=folder/'adapter'
    subprocess.run(['xcrun','clang','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
        str(adapter),'-o',str(adapter_binary)],check=True)
    subprocess.run([str(adapter_binary)],check=True)
    print('PASS: production Wine adapter preserves full size/address, propagates failure and rejects/cleans a changed backend result')
    executable=folder/'check'
    subprocess.run(['xcrun','clang','-std=gnu11','-Wall','-Wextra','-Werror','-pthread',
        '-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(NATIVE),str(NATIVE/'steam_cef_guard.c'),
        str(NATIVE/'steam_cef_pools.c'),str(ROOT/'tests/host/fixtures/SteamCEFPoolsCheck.c'),'-o',str(executable)],check=True)
    subprocess.run([str(executable),str(image)],check=True)
    # ASan itself can occupy the fixed high band. Repeat without its shadow
    # mappings to corroborate the actual Mach reservation when the host can.
    executable=folder/'kernel-check'
    subprocess.run(['xcrun','clang','-std=gnu11','-Wall','-Wextra','-Werror','-pthread','-I'+str(NATIVE),
        str(NATIVE/'steam_cef_guard.c'),str(NATIVE/'steam_cef_pools.c'),
        str(ROOT/'tests/host/fixtures/SteamCEFPoolsCheck.c'),'-o',str(executable)],check=True)
    subprocess.run([str(executable),str(image)],check=True)
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    subprocess.run(['xcrun','clang','-arch','arm64','-isysroot',sdk,'-miphoneos-version-min=18.0',
        '-std=gnu11','-Wall','-Wextra','-Werror','-fsyntax-only',str(NATIVE/'steam_cef_pools.c')],check=True)
    syntax=folder/'native-types.c'
    syntax.write_text('#include <stddef.h>\n#include <stdint.h>\n#include "ntstatus.h"\n#include "windef.h"\n#include "winbase.h"\n#include "winternl.h"\n'
        'extern NTSTATUS allocate_virtual_memory(void **,SIZE_T *,ULONG,ULONG,ULONG_PTR,ULONG_PTR,ULONG_PTR,ULONG);\n'+backend+'\n')
    subprocess.run(['xcrun','clang','-arch','arm64','-isysroot',sdk,'-miphoneos-version-min=18.0',
        '-std=gnu11','-fsyntax-only','-D__WINESRC__','-D_NTSYSTEM_','-DWINE_UNIX_LIB',
        '-I'+str(ROOT/'wine/include'),str(syntax)],check=True)
    print('PASS: production Wine adapter types compile against real Wine headers and iOS SDK')
print('PASS: actual pinned Valve image verified' if args.official_image else 'PASS: offline public-image fingerprint fixtures verified')
print('Host kernel/component proof only; Steam/CEF initialization, IPA build and iPad rendering remain UNRUN.')
