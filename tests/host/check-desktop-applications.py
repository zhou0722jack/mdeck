#!/usr/bin/env python3
"""Exercise desktop discovery on a disposable prefix and the production Wine/frame predicates."""
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app/Madeira'
PATCH = ROOT / 'build/windows-runtime/patches/0002-desktop-applications.patch'


def function(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


project = (ROOT / 'app/Madeira.xcodeproj/project.pbxproj').read_text()
assert project.count('/* DesktopApplications.swift in Sources */') == 2
bridge = (APP / 'WineProcessBridge.m').read_text()
seed = function(bridge, 'void madeira_seed_prefix_if_needed(')
assert seed.index('madeira_japanese_prefix(') < seed.index('madeira_prepare_desktop_applications(prefix_path)')
library = (APP / 'Library.swift').read_text()
gate = library[library.index('} else if launching && activeEntry?.desktop == true {'):library.index('} else if launching {', library.index('} else if launching && activeEntry?.desktop == true {'))]
assert 'winios_desktop_is_ready()' in gate and 'desktop-ready-frame' in gate
assert 'madeira_frame_count()' not in gate and 'winios_surface_present_count()' not in gate
assert 'Show game view' in library and 'launchSlow = true' in gate
assert 'build/windows-runtime/apply-patches.sh' in (ROOT / 'build/wine-i386/build.sh').read_text()

with tempfile.TemporaryDirectory(prefix='mdeck-desktop-apps-') as temporary:
    temp = Path(temporary)
    swift_fixture = ROOT / 'tests/host/fixtures/DesktopApplicationsCheck.swift'
    binary = temp / 'discovery'
    sources = [APP / 'DesktopApplications.swift', APP / 'SteamKeyValues.swift', APP / 'Localization.swift']
    subprocess.run(['xcrun', 'swiftc', '-parse-as-library', *map(str, sources), str(swift_fixture), '-o', str(binary)], check=True)
    subprocess.run([str(binary), str(temp / 'prefix-fixture')], check=True)
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    stubs = temp / 'IOSDependencies.swift'
    stubs.write_text('import Foundation\nfinal class LogStore { static let shared=LogStore(); func log(_ s:String){} }\n'
                     'func wine_process_is_running()->Int32{0}\nfunc wineserver_is_running()->Int32{0}\n')
    subprocess.run(['xcrun', 'swiftc', '-typecheck', '-sdk', sdk, '-target', 'arm64-apple-ios18.0',
                    *map(str, sources), str(stubs)], check=True)

    # Apply to a disposable copy; never modify the user's Wine submodule.
    wine = temp / 'wine'
    wine.mkdir()
    subprocess.run(['git', 'init', '-q', str(wine)], check=True)
    originals = {}
    for name in ['programs/explorer/desktop.c', 'dlls/shell32/shelllink.c']:
        originals[name] = subprocess.check_output(['git', '-C', str(ROOT / 'wine'), 'show', 'HEAD:' + name], text=True)
        target = wine / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(originals[name])
    subprocess.run(['git', '-C', str(wine), 'apply', '--check', str(PATCH)], check=True)
    subprocess.run(['git', '-C', str(wine), 'apply', str(PATCH)], check=True)
    explorer = (wine / 'programs/explorer/desktop.c').read_text()
    shell = (wine / 'dlls/shell32/shelllink.c').read_text()
    ready = explorer[explorer.index('/* Only the requested shell'):explorer.index('if ((shell32 = LoadLibraryW', explorer.index('/* Only the requested shell'))]
    assert 'name && !wcsicmp( name, L"shell" )' in ready
    assert explorer.index('initialize_launchers( hwnd );', explorer.index('void manage_desktop(')) < explorer.index('L"MDeckDesktopReady"')

    # An independent Shell Link reader checks sizes, UTF-16 strings, offsets,
    # argument separation and the ExtraData terminal against MS-SHLLINK.
    exported = temp / 'prefix-fixture/links'
    expected = json.loads((exported / 'expected.json').read_text())
    for item in expected:
        data = (exported / item['file']).read_bytes()
        assert struct.unpack_from('<I', data)[0] == 76
        assert data[4:20] == bytes.fromhex('0114020000000000c000000000000046')
        flags = struct.unpack_from('<I', data, 20)[0]
        assert flags == 0xb6 and struct.unpack_from('<I', data, 60)[0] == 1
        size, header, info_flags, volume, local, network, suffix, unicode, unicode_suffix = struct.unpack_from('<9I', data, 76)
        assert header == 36 and info_flags == 1 and network == 0 and volume == 36
        assert 36 <= local < suffix < unicode < unicode_suffix < size <= len(data) - 76
        info = data[76:76 + size]
        def utf16z(at):
            end = at
            while info[end:end+2] != b'\0\0':
                end += 2
                assert end + 2 <= size
            return info[at:end].decode('utf-16le')
        assert utf16z(unicode) == item['target'] and utf16z(unicode_suffix) == ''
        offset, strings = 76 + size, []
        for _ in range(3):
            count = struct.unpack_from('<H', data, offset)[0]
            offset += 2
            strings.append(data[offset:offset+count*2].decode('utf-16le'))
            offset += count * 2
        assert strings[1:] == [item['workingDirectory'], item['arguments']]
        assert data[offset:] == b'\0\0\0\0'

    # Execute Wine's actual patched Stream_LoadLocation against the same links.
    # This caught the original Wine reader choosing the lossy ANSI fallback.
    def typedef(name, end):
        at = shell.index(name)
        return shell[at:shell.index(end, at)+len(end)]
    reader = temp / 'read-link.c'
    reader.write_text(r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint16_t WCHAR;
typedef uint32_t DWORD, ULONG;
typedef int HRESULT, BOOL;
typedef char *LPSTR;
typedef const char *LPCSTR;
typedef WCHAR *LPWSTR;
typedef void *LPVOID;
typedef FILE IStream;
#define FALSE 0
#define TRUE 1
#define S_OK 0
#define E_FAIL (-1)
#define FAILED(x) ((x)<0)
#define TRACE(...) ((void)0)
''' + typedef('typedef struct _LOCATION_INFO', '} LOCATION_INFO;') + '\n'
        + typedef('typedef struct _LOCAL_VOLUME_INFO', '} LOCAL_VOLUME_INFO;') + '\n'
        + typedef('typedef struct volume_info_t', '} volume_info;') + r'''
static HRESULT Stream_ReadChunk(IStream *stream, LPVOID *out) {
    uint32_t n;
    if (fread(&n,4,1,stream)!=1 || n<4 || n>4*1024*1024) return E_FAIL;
    char *p=malloc(n); if(!p) return E_FAIL; memcpy(p,&n,4);
    if(fread(p+4,1,n-4,stream)!=n-4) { free(p); return E_FAIL; }
    *out=p; return S_OK;
}
static BOOL Stream_LoadVolume(LOCAL_VOLUME_INFO *input, volume_info *volume) { (void)input;(void)volume;return TRUE; }
static LPWSTR Stream_LoadPath(LPCSTR p,DWORD maxlen) {
    size_t len=strnlen(p,maxlen); WCHAR *out=calloc(len+1,sizeof(WCHAR));
    for(size_t i=0;i<len;i++) out[i]=(unsigned char)p[i]; return out;
}
''' + function(shell, 'static HRESULT Stream_LoadLocation(') + r'''
int main(int argc,char **argv) {
    assert(argc==2); FILE *f=fopen(argv[1],"rb");assert(f);assert(!fseek(f,76,SEEK_SET));
    volume_info v={0}; WCHAR *path=NULL;
    assert(Stream_LoadLocation(f,&v,&path)==S_OK && path);
    for(size_t i=0;path[i];i++) fwrite(&path[i],sizeof(WCHAR),1,stdout);
    free(path);fclose(f);return 0;
}
''')
    reader_binary = temp / 'read-link'
    subprocess.run(['xcrun', 'clang', '-std=c11', '-Wall', '-Wextra', '-Werror', str(reader), '-o', str(reader_binary)], check=True)
    for item in expected:
        actual = subprocess.check_output([str(reader_binary), str(exported / item['file'])]).decode('utf-16le')
        assert actual == item['target'], (item, actual)
    print('PASS: independent Shell Link layout and actual Wine path reader preserve Unicode targets, arguments and working folders')

    launcher_fixture = (ROOT / 'tests/host/fixtures/DesktopShellCheck.c').read_text()
    functions = '\n'.join(function(explorer, signature) for signature in [
        'static BOOL add_launcher(', 'static void free_launcher( struct launcher *launcher )\n{',
        'static BOOL remove_launcher(', 'static BOOL process_changes('])
    launcher_fixture = launcher_fixture.replace('/* PRODUCTION_LAUNCHERS */', functions)
    for label, watcher in [('fixed', explorer), ('original', originals['programs/explorer/desktop.c'])]:
        source = temp / (label + '-shell.c')
        source.write_text(launcher_fixture.replace('/* PRODUCTION_WATCHER */', function(watcher, 'static DWORD CALLBACK watch_desktop_folders(')))
        exe = source.with_suffix('')
        subprocess.run(['xcrun', 'clang', '-std=c11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(exe)], check=True)
        result = subprocess.run([str(exe)])
        assert result.returncode == (0 if label == 'fixed' else 1), label
    print('PASS: generic icon, same-path replacement, modified-link refresh and watcher rearm; original watcher reproduces overlap')

    process = (ROOT / 'build/ntdll-unix/process_ios.c').read_text()
    create = function(process, 'NTSTATUS WINAPI NtCreateUserProcess(')
    assert 'child_extra_cmdline( params->CommandLine.Buffer' in create
    assert 'getenv( "MADEIRA_CHILD_ARGS_FIRST" )' in create
    argument_source = temp / 'child-arguments.c'
    argument_source.write_text(r'''
#include <stdint.h>
#include <string.h>
#include <assert.h>
typedef uint16_t WCHAR;
''' + function(process, 'static int child_extra_cmdline(') + r'''
int main(void) {
    const WCHAR command[]=u"\"C:\\Program Files\\Steam Client\\Steam.exe\" -applaunch 570 -novid \"中文 参数\"";
    const WCHAR before[]=u"\"C:\\Program Files\\Steam Client\\Steam.exe\" -no-cef-sandbox -cef-disable-gpu -applaunch 570 -novid \"中文 参数\"";
    const WCHAR after[]=u"\"C:\\Program Files\\Steam Client\\Steam.exe\" -applaunch 570 -novid \"中文 参数\" -no-cef-sandbox -cef-disable-gpu";
    const char *extra="-no-cef-sandbox -cef-disable-gpu";
    WCHAR out[512];int length=sizeof(command)/sizeof(WCHAR)-1;
    int n=child_extra_cmdline(command,length,extra,1,out,512);
    assert(n==(int)(sizeof(before)/sizeof(WCHAR)-1) && !memcmp(out,before,sizeof(before)));
    n=child_extra_cmdline(command,length,extra,0,out,512);
    assert(n==(int)(sizeof(after)/sizeof(WCHAR)-1) && !memcmp(out,after,sizeof(after)));
    assert(child_extra_cmdline(command,length,extra,1,out,5)==-1);
    assert(child_extra_cmdline(NULL,length,extra,1,out,512)==-1);
    const WCHAR leading[]=u"  steam.exe -applaunch 730";
    const WCHAR expected[]=u"  steam.exe -safe -applaunch 730";
    child_extra_cmdline(leading,sizeof(leading)/sizeof(WCHAR)-1,"-safe",1,out,512);
    assert(!memcmp(out,expected,sizeof(expected)));
    return 0;
}
''')
    argument_binary = temp / 'child-arguments'
    subprocess.run(['xcrun', 'clang', '-std=c11', '-Wall', '-Wextra', '-Werror', str(argument_source), '-o', str(argument_binary)], check=True)
    subprocess.run([str(argument_binary)], check=True)
    subprocess.run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios18.0', '-std=c11',
                    '-fsyntax-only', '-Wall', '-Wextra', '-Werror', str(argument_source)], check=True)
    print('PASS: desktop Steam compatibility options precede -applaunch; quoted/Unicode game arguments and ordinary append behavior survive')

    # Compile the real readiness atomics/predicate with a small macOS view
    # stand-in; surface tagging and the driver polling branch are production.
    native = (APP / 'Winios/Winios.m').read_text()
    driver = (ROOT / 'build/win32u-unix/driver_ios.c').read_text()
    state = native[native.index('static _Atomic(uintptr_t) g_desktop_ready_hwnd;'):native.index('/* A game\'s main window can be shown minimized')]
    session = function(native, 'void winios_session_reset(')
    resets = session[session.index('atomic_fetch_add(&g_desktop_ready_generation'):session.index('atomic_store(&g_size_game_hwnd')]
    present = function(native, 'int winios_surface_present(')
    captures = present[present.index('    const uintptr_t readyDesktop'):present.index('    winios_census_note_present')]
    commit = present[present.index('            if (readyDesktop =='):present.index('            if (pending) { l.hidden')]
    pump = function(driver, 'static BOOL winios_drv_process_events(')
    poll = pump[pump.index('    if (winios_desktop_mode()'):pump.index('    if (ios_show_foreground)')]
    objc = temp / 'ready.m'
    objc.write_text(r'''
#import <Foundation/Foundation.h>
#import <QuartzCore/QuartzCore.h>
#include <assert.h>
#include <stdatomic.h>
typedef void *HWND;
typedef uint16_t WCHAR;
@interface DesktopView : NSObject
@property BOOL hidden;
@property id window;
@property CGRect bounds;
@end
@implementation DesktopView
@end
static DesktopView *g_compositor_view;
static NSMutableDictionary *g_layers;
extern int winios_note_desktop_ready(void *) __attribute__((weak));
''' + state + '\n' + function(native, 'int winios_window_has_visible_frame(') + '\n'
        + function(native, 'int winios_desktop_is_ready(') + '\n'
        + 'static void reset(void) {\n' + resets + 'g_desktop_ready_frame=NO;\n}\n'
        + 'static dispatch_block_t surface(HWND hwnd) {\n' + captures + 'return ^{\n' + commit + '};\n}\n' + r'''
static int mode=1,property,redraws;
#define RDW_INVALIDATE 1
#define RDW_ERASE 2
#define RDW_ALLCHILDREN 4
static int winios_desktop_mode(void){return mode;}
static HWND get_desktop_window(void){return (HWND)200;}
static uintptr_t NtUserGetProp(HWND hwnd,const WCHAR *key) {
    assert(hwnd==(HWND)200 && key[0]=='M' && key[16]=='y' && !key[17]); return property;
}
static void NtUserRedrawWindow(HWND hwnd,void *r,int region,unsigned flags) {
    (void)r;(void)region;assert(hwnd==(HWND)200 && flags==7);redraws++;
}
static void pump(void) {
''' + poll + r'''
}
int main(void) { @autoreleasepool {
    g_compositor_view=[DesktopView new];g_compositor_view.window=@1;g_compositor_view.bounds=CGRectMake(0,0,800,600);
    CALayer *layer=[CALayer layer];layer.frame=CGRectMake(0,0,800,600);layer.contents=@1;
    g_layers=[@{@200:layer} mutableCopy];reset();
    dispatch_block_t early=surface((HWND)200);
    pump();assert(!winios_desktop_is_ready() && !redraws);
    property=1;pump();pump();assert(redraws==1 && !winios_desktop_is_ready());
    early();assert(!winios_desktop_is_ready());
    surface((HWND)300)();assert(!winios_desktop_is_ready());
    surface((HWND)200)();assert(winios_desktop_is_ready());
    layer.hidden=YES;assert(!winios_desktop_is_ready());layer.hidden=NO;
    layer.frame=CGRectMake(-1000,-1000,100,100);assert(!winios_desktop_is_ready());layer.frame=g_compositor_view.bounds;
    layer.contents=nil;assert(!winios_desktop_is_ready());layer.contents=@1;
    g_compositor_view.hidden=YES;assert(!winios_desktop_is_ready());g_compositor_view.hidden=NO;
    dispatch_block_t previous=surface((HWND)200);reset();assert(!winios_desktop_is_ready());
    mode=0;pump();assert(!atomic_load(&g_desktop_ready_hwnd));mode=1;pump();
    previous();assert(!winios_desktop_is_ready());surface((HWND)200)();assert(winios_desktop_is_ready());
    assert(!winios_note_desktop_ready(NULL));
} return 0; }
''')
    ready_binary = temp / 'ready'
    subprocess.run(['xcrun', 'clang', '-fobjc-arc', '-fblocks', '-Wall', '-Wextra', '-Werror', str(objc),
                    '-framework', 'Foundation', '-framework', 'QuartzCore', '-framework', 'CoreGraphics', '-o', str(ready_binary)], check=True)
    subprocess.run([str(ready_binary)], check=True)
    print('PASS: backdrop/queued/other-window/previous-session frames cannot reveal desktop; initialized shell plus visible new paint can')

    # The actual UIKit predicate and surface-ready branch also typecheck for iOS.
    ios_ready = temp / 'ready-ios.m'
    ios_ready.write_text('#import <UIKit/UIKit.h>\n#include <stdatomic.h>\n#include <stdio.h>\n'
                         'static UIView *g_compositor_view;\nstatic NSMutableDictionary *g_layers;\n' + state + '\n'
                         + function(native, 'int winios_window_has_visible_frame(') + '\n'
                         + function(native, 'int winios_desktop_is_ready(') + '\n'
                         + 'dispatch_block_t desktopSurface(void *hwnd) {\n' + captures + 'return ^{\n' + commit + '};\n}\n')
    subprocess.run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios18.0', '-fobjc-arc',
                    '-fsyntax-only', '-Wall', '-Wextra', '-Werror', str(ios_ready)], check=True)

    # Deliberate source drift must fail instead of quietly shipping an unpatched shell.
    broken = wine / 'programs/explorer/desktop.c'
    broken.write_text(originals['programs/explorer/desktop.c'].replace('launcher->icon = extract_icon( link );', 'changed();'))
    (wine / 'dlls/shell32/shelllink.c').write_text(originals['dlls/shell32/shelllink.c'])
    check = subprocess.run(['git', '-C', str(wine), 'apply', '--check', str(PATCH)], capture_output=True)
    assert check.returncode != 0
print('PASS: production Swift including refresh monitor and native bridge typecheck for iOS; patch rejects source drift')
print('No Wine execution, IPA build, signing, installation or physical-device test performed.')
