#!/usr/bin/env python3
"""Exercise the real NSIS automation policy/driver adapter without an installer."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'app/Madeira/SteamClient.swift').read_text()
assert 'SteamClient.configureSession(profile)' in (ROOT / 'app/Madeira/ContentView.swift').read_text()
assert 'setenv("MADEIRA_CHILD_ARGS", "steam.exe " + childArguments, 1)' in source
assert 'compatibilityArguments' in source
driver = (ROOT / 'build/win32u-unix/driver_ios.c').read_text()
assert '#include "steam_installer_ios.h"' in driver and 'ios_steam_installer_poll();' in driver
process = (ROOT / 'build/ntdll-unix/process_ios.c').read_text()
rules = []
for signature in ['static int ios_image_name_is(', 'static int ios_setup_steam_autolaunch_deferred(', 'static const char *child_extra_args(']:
    start=process.index(signature); end=process.index('\n}',start)+2
    rules.append(process[start:end])
classes = (ROOT / 'build/win32u-unix/class_ios.c').read_text()
start = classes.index('INT WINAPI NtUserGetClassName(')
end = classes.index('\n}', start) + 2
class_reader = classes[start:end]
edit = (ROOT / 'wine/dlls/user32/edit.c').read_text()
start = edit.index('static INT EDIT_WM_GetText(')
end = edit.index('\n}', start) + 2
edit_reader = edit[start:end]

program = r'''
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <assert.h>
typedef uint16_t WCHAR;
typedef uintptr_t HWND;
typedef unsigned ULONG,DWORD;
typedef unsigned UINT;
typedef int INT,BOOL,NTSTATUS;
typedef struct { WCHAR *Buffer; unsigned short Length,MaximumLength; } UNICODE_STRING;
typedef struct { UNICODE_STRING ImagePathName; } RTL_USER_PROCESS_PARAMETERS;
struct { struct { RTL_USER_PROCESS_PARAMETERS *ProcessParameters; } *Peb; } teb;
#define NtCurrentTeb() (&teb)
#define ARRAY_SIZE(a) (sizeof(a)/sizeof(*(a)))
#define FALSE 0
#define TRUE 1
#define GA_PARENT 1
#define GWLP_ID (-12)
#define IDOK 1
#define BN_CLICKED 0
#define WM_COMMAND 0x111
#define MAKEWPARAM(a,b) ((uintptr_t)(a)|((uintptr_t)(b)<<16))
typedef intptr_t LPARAM;
typedef intptr_t LRESULT;
typedef WCHAR *LPWSTR;
typedef char *LPSTR;
#define WM_GETTEXT 0x0d
#define SMTO_ABORTIFHUNG 2
#define CP_ACP 0
#define WM_USER 0x400
#define GWL_STYLE (-16)
#define BS_TYPEMASK 0xf
#define BS_AUTOCHECKBOX 3
#define BS_CHECKBOX 2
#define BM_GETCHECK 0xf0
#define BM_SETCHECK 0xf1
#define BST_UNCHECKED 0
static uint64_t tick_ms;
static unsigned stage,posted,ready=1,valid_directory=1,wrong_thread,dialog_enabled=1,checked=1,unchecked,progress_updates;
static WCHAR *wide(const char *s) {
    static WCHAR buffers[8][300];static unsigned index;
    WCHAR *b=buffers[index++%8];unsigned i;
    for(i=0;s[i]&&i<299;i++) b[i]=(unsigned char)s[i];
    b[i]=0;return b;
}
static int copy_text(WCHAR *out,unsigned cap,const char *s) {
    unsigned i;for(i=0;s[i]&&i+1<cap;i++)out[i]=(unsigned char)s[i];
    out[i]=0;return i;
}
typedef struct { WCHAR *text; } EDITSTATE;
static void lstrcpynW(WCHAR *out,const WCHAR *in,int cap) {
    int i=0;for(;i+1<cap && in[i];i++)out[i]=in[i];out[i]=0;
}
static int lstrlenW(const WCHAR *s) {int n=0;while(s[n])n++;return n;}
static int WideCharToMultiByte(unsigned a,unsigned b,const WCHAR *c,int d,char *e,int f,void *g,void *h) {
    (void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;(void)h;
    assert(!"expected Unicode Edit read");return 0;
}
/* REAL_EDIT_READER */
static unsigned GetCurrentThreadId(void) {return 24;}
static unsigned get_window_thread(HWND h,void *unused) {(void)h;(void)unused;return wrong_thread?99:24;}
static int is_window_visible(HWND h) {(void)h;return 1;}
static int NtUserIsWindowEnabled(HWND h) {return h==2?dialog_enabled:ready;}
struct object_lock { int pending; };
#define OBJECT_LOCK_INIT {0}
#define MAX_ATOM_LEN 255
#define STATUS_PENDING 0x103
#define ERROR_INSUFFICIENT_BUFFER 122
#define WINAPI
#define min(a,b) ((a)<(b)?(a):(b))
#define TRACE(...) ((void)real)
typedef struct { unsigned name_len,name_offset; WCHAR name[32]; } class_shm_t;
static void RtlSetLastWin32Error(unsigned e) {(void)e;}
static NTSTATUS get_shared_window_class(HWND h,struct object_lock *lock,const class_shm_t **out) {
    static class_shm_t shared;
    if(lock->pending) return 0;
    const char *c=h==3||h==6?"Button":h==5?"Edit":h==7?"msctls_progress32":"#32770";
    shared.name_len=copy_text(shared.name,32,c)*2;shared.name_offset=0;*out=&shared;
    lock->pending=1;return STATUS_PENDING;
}
/* REAL_CLASS_READER */
static int NtUserBuildHwndList(int a,HWND parent,int c,int d,unsigned thread,unsigned cap,HWND *out,ULONG *n) {
    (void)a;(void)c;(void)d;(void)thread;assert(cap>=6);
    if(!parent){out[0]=2;out[1]=1;*n=2;}
    else{assert(parent==2);out[0]=3;out[1]=4+stage*10;out[2]=5;out[3]=6;out[4]=7;out[5]=1;*n=6;}return 0;
}
static HWND NtUserGetAncestor(HWND h,unsigned kind) {(void)h;assert(kind==GA_PARENT);return 2;}
static int get_window_long(HWND h,int offset) {
    if(offset==GWL_STYLE)return h==6?BS_AUTOCHECKBOX:0;
    assert(offset==GWLP_ID);return h==3?1:0;
}
static int NtUserInternalGetWindowText(HWND h,WCHAR *out,unsigned cap) {
    const char *s=h==6?"Run Steam":h==5?"": /* Edit's WND.text is empty even when EDITSTATE.text is not. */
        stage<2?"&Next >":stage==2?"&Install":"&Finish";
    return copy_text(out,cap,s);
}
static void ios_steam_installer_poll(void);
static LRESULT send_message_timeout(HWND h,unsigned msg,uintptr_t cap,LPARAM buffer,unsigned flags,unsigned timeout,int ansi) {
    static int depth;
    assert(++depth==1);
    if(h==6){
        assert(flags==SMTO_ABORTIFHUNG&&!ansi);
        if(msg==BM_SETCHECK){checked=(unsigned)cap;unchecked++;depth--;return 0;}
        assert(msg==BM_GETCHECK);depth--;return checked;
    }
    if(h==7){assert(msg==WM_USER+7||msg==WM_USER+8);depth--;return msg==WM_USER+8?42:cap?0:100;}
    assert(h==5 && msg==WM_GETTEXT && cap==260 && flags==SMTO_ABORTIFHUNG && timeout==250 && !ansi);
    WCHAR text[260];
    copy_text(text,260,valid_directory?"C:\\Program Files\\Steam Client":"D:\\other");
    EDITSTATE es={text};
    if(teb.Peb) for(unsigned i=0;i<64;i++)ios_steam_installer_poll();
    LRESULT result=EDIT_WM_GetText(&es,(int)cap,(LPWSTR)buffer,TRUE);
    depth--;return result;
}
static int NtUserPostMessage(HWND h,unsigned msg,uintptr_t w,LPARAM l) {
    assert(h==2&&msg==WM_COMMAND&&w==1&&l==3);assert(stage<4);posted++;stage++;return 1;
}
static uint64_t ios_tiny_now_ns(void) {return tick_ms*1000000;}
#include "steam_installer_ios.h"
void winios_steam_setup_note(int step,int percent,int blocked) {
    assert(step>=0&&step<=5&&percent>=-1&&percent<=100&&blocked>=0&&blocked<=3);progress_updates++;
}
/* CHILD_RULES */
static void poll_for(unsigned count) {for(unsigned i=0;i<count;i++){tick_ms+=20;ios_steam_installer_poll();}}
int main(void) {
    WCHAR cls[32];UNICODE_STRING name={.Buffer=cls,.Length=0,.MaximumLength=sizeof(cls)};
    assert(NtUserGetClassName(2,0,&name)==6 && name.Length==0);
    assert(!steam_setup_ascii_equal(cls,name.Length/2,"#32770")); /* Build 16's old test rejects a real dialog */
    assert(steam_setup_class(2,"#32770") && steam_setup_class(3,"Button"));
    WCHAR folder[260];
    assert(NtUserInternalGetWindowText(5,folder,260)==0); /* Build 17's old directory read fails. */
    assert(send_message_timeout(5,WM_GETTEXT,260,(LPARAM)folder,SMTO_ABORTIFHUNG,250,FALSE)>0);
    assert(steam_setup_ascii_equal(folder,lstrlenW(folder),"C:\\Program Files\\Steam Client"));
    struct steam_setup_state state={0};
    const uint16_t zh_next[]={0x4e0b,0x4e00,0x6b65,'(','&','N',')','>'};
    const uint16_t zh_install[]={0x5b89,0x88c5,'(','&','I',')'};
    const uint16_t zh_finish[]={0x5b8c,0x6210,'(','&','F',')'};
    assert(steam_setup_role(zh_next,ARRAY_SIZE(zh_next))==STEAM_SETUP_NEXT);
    assert(steam_setup_role(zh_install,ARRAY_SIZE(zh_install))==STEAM_SETUP_INSTALL);
    assert(steam_setup_role(zh_finish,ARRAY_SIZE(zh_finish))==STEAM_SETUP_FINISH);
    assert(steam_setup_role(wide("Retry"),5)==STEAM_SETUP_NONE);
    assert(steam_setup_observe(&state,10,STEAM_SETUP_NEXT,1,0,0)==0);
    assert(steam_setup_observe(&state,10,STEAM_SETUP_NEXT,1,0,699)==0);
    assert(steam_setup_observe(&state,10,STEAM_SETUP_NEXT,1,0,700)==STEAM_SETUP_NEXT);
    steam_setup_posted(&state,STEAM_SETUP_NEXT);
    assert(steam_setup_observe(&state,10,STEAM_SETUP_NEXT,1,0,5000)==0);
    assert(steam_setup_observe(&state,20,STEAM_SETUP_NEXT,0,0,5000)==0);
    assert(steam_setup_observe(&state,20,STEAM_SETUP_NEXT,1,0,5100)==0);
    assert(steam_setup_observe(&state,20,STEAM_SETUP_NEXT,1,0,5800)==STEAM_SETUP_NEXT);
    steam_setup_posted(&state,STEAM_SETUP_NEXT);
    assert(steam_setup_observe(&state,30,STEAM_SETUP_INSTALL,1,0,6000)==0);
    assert(steam_setup_observe(&state,30,STEAM_SETUP_INSTALL,1,0,7000)==0);
    assert(steam_setup_observe(&state,30,STEAM_SETUP_INSTALL,1,1,7000)==STEAM_SETUP_INSTALL);
    steam_setup_posted(&state,STEAM_SETUP_INSTALL);
    assert(steam_setup_observe(&state,40,STEAM_SETUP_FINISH,1,1,10000)==0);
    assert(steam_setup_observe(&state,40,STEAM_SETUP_FINISH,1,1,10700)==STEAM_SETUP_FINISH);
    steam_setup_posted(&state,STEAM_SETUP_FINISH);
    assert(steam_setup_observe(&state,50,STEAM_SETUP_FINISH,1,1,20000)==0);
    puts("PASS: two distinct Next pages, enabled/stable controls, expected directory, Install then Finish; unknown pages stay manual");
    RTL_USER_PROCESS_PARAMETERS params={0};
    __typeof__(*teb.Peb) peb={&params};teb.Peb=&peb;
    params.ImagePathName.Buffer=wide("C:\\other\\SteamSetup.exe");params.ImagePathName.Length=48;
    setenv("MADEIRA_STEAM_AUTOINSTALL","1",1);setenv("MADEIRA_STEAM_CONTROLLED_SETUP","1",1);poll_for(300);assert(!posted);
    params.ImagePathName.Buffer=wide("C:\\Madeira\\Installers\\SteamSetup.exe");params.ImagePathName.Length=72;
    wrong_thread=1;poll_for(300);assert(!posted);wrong_thread=0;
    dialog_enabled=0;poll_for(300);assert(!posted);dialog_enabled=1;
    setenv("MADEIRA_STEAM_AUTOINSTALL","0",1);poll_for(300);assert(!posted);
    setenv("MADEIRA_STEAM_AUTOINSTALL","1",1);
    for(unsigned i=0;i<2000 && posted<2;i++)poll_for(1);
    assert(posted==2 && stage==2);
    valid_directory=0;poll_for(300);assert(posted==2);
    valid_directory=1;poll_for(3000);
    assert(posted==4&&stage==4&&checked==0&&unchecked==1&&progress_updates>0);poll_for(1000);assert(posted==4);
    puts("PASS: real driver adapter posts four exact commands only to the pinned installer GUI thread, without focus or coordinates");
    WCHAR *steam=wide("C:\\Program Files\\Steam Client\\steam.exe");
    unsigned length=0;while(steam[length])length++;
    assert(child_extra_args("steam.exe -no-cef-sandbox -cef-disable-gpu",steam,length));
    assert(!child_extra_args("steam.exe -cef-disable-gpu",wide("C:\\other.exe"),12));
    WCHAR *setup=wide("C:\\Madeira\\Installers\\SteamSetup.exe"),*controller=wide("C:\\Madeira\\Installers\\SteamBootstrap.exe");
    int setup_len=lstrlenW(setup),controller_len=lstrlenW(controller);
    assert(ios_setup_steam_autolaunch_deferred("1",setup,setup_len,steam,length));
    assert(!ios_setup_steam_autolaunch_deferred("0",setup,setup_len,steam,length));
    assert(!ios_setup_steam_autolaunch_deferred("1",controller,controller_len,steam,length));
    assert(!ios_setup_steam_autolaunch_deferred("1",steam,length,steam,length));
    puts("PASS: existing child argument rule selects steam.exe for installer/updater restarts, not unrelated executables");
}
'''.replace('/* CHILD_RULES */','\n'.join(rules)).replace('/* REAL_CLASS_READER */',class_reader).replace('/* REAL_EDIT_READER */',edit_reader)
with tempfile.TemporaryDirectory(prefix='mdeck-steam-setup-') as tmp:
    file=Path(tmp)/'check.c';file.write_text(program)
    binary=Path(tmp)/'check'
    subprocess.run(['xcrun','clang','-std=gnu11','-Wall','-Wextra','-Werror',
                    '-I',str(ROOT/'build/win32u-unix'),str(file),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
    subprocess.run(['xcrun','--sdk','iphoneos','clang','-target','arm64-apple-ios18.0',
                    '-std=gnu11','-Wall','-Wextra','-Werror','-fsyntax-only',
                    '-I',str(ROOT/'build/win32u-unix'),str(file)],check=True)
    method=source[source.index('    static func configureSession('):source.index('    static func cancelPreparation(')]
    swift=Path(tmp)/'Session.swift'
    swift.write_text('''import Foundation
struct LibraryEntry { var id: Int }
final class LogStore { static let shared=LogStore(); func log(_ text:String) {} }
enum SteamClient {
    static let installerID=1
    static let clientArguments="-no-cef-sandbox -cef-disable-gpu"
    static func owns(_ entry:LibraryEntry)->Bool { entry.id==1 || entry.id==2 }
''' + method + r'''}
@main struct Check {
    static func main() {
        unsetenv("MADEIRA_CHILD_ARGS"); unsetenv("MADEIRA_STEAM_AUTOINSTALL")
        SteamClient.configureSession(LibraryEntry(id:3))
        precondition(getenv("MADEIRA_CHILD_ARGS")==nil)
        SteamClient.configureSession(LibraryEntry(id:1))
        precondition(String(cString:getenv("MADEIRA_CHILD_ARGS"))=="steam.exe "+SteamClient.clientArguments)
        precondition(String(cString:getenv("MADEIRA_STEAM_AUTOINSTALL"))=="1")
        setenv("MADEIRA_CHILD_ARGS","custom.exe --user",1)
        setenv("MADEIRA_STEAM_AUTOINSTALL","0",1)
        SteamClient.configureSession(LibraryEntry(id:1))
        precondition(String(cString:getenv("MADEIRA_CHILD_ARGS"))=="steam.exe "+SteamClient.clientArguments)
        precondition(String(cString:getenv("MADEIRA_STEAM_AUTOINSTALL"))=="1")
        precondition(String(cString:getenv("MADEIRA_STEAM_CONTROLLED_SETUP"))=="1")
        unsetenv("MADEIRA_STEAM_AUTOINSTALL")
        SteamClient.configureSession(LibraryEntry(id:2))
        precondition(String(cString:getenv("MADEIRA_STEAM_AUTOINSTALL"))=="0")
        precondition(getenv("MADEIRA_STEAM_CONTROLLED_SETUP")==nil)
        let flags=SteamClient.compatibilityArguments("-console \"-cef-disable-gpu\"")
        precondition(flags=="-console \"-cef-disable-gpu\" -no-cef-sandbox")
        precondition(SteamClient.compatibilityArguments(flags)==flags)
        let nested=SteamClient.compatibilityArguments("-name \"x -cef-disable-gpu y\"")
        precondition(nested.hasSuffix(" -no-cef-sandbox -cef-disable-gpu"))
        print("PASS: production Swift config guarantees Steam compatibility flags and controlled setup, scopes non-Steam entries and deduplicates switches")
    }
}
''')
    subprocess.run(['xcrun','swiftc','-parse-as-library',str(swift),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
print('No installer, Wine session, IPA build or physical-device test performed.')
