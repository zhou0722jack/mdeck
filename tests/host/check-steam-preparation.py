#!/usr/bin/env python3
"""Run the real setup controller against a deterministic Win32 API fixture."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HEADER = r'''
#include <stdint.h>
#include <stddef.h>
typedef uint16_t WCHAR;
typedef uint32_t DWORD;
typedef size_t SIZE_T;
typedef int BOOL;
typedef uintptr_t HANDLE;
typedef HANDLE HMODULE;
typedef HANDLE HWINSTA;
typedef HANDLE HDESK;
typedef void (*FARPROC)(void);
#define WINAPI
#undef NULL
#define NULL 0
typedef struct { DWORD cb; } STARTUPINFOW;
typedef struct { HANDLE hProcess,hThread; } PROCESS_INFORMATION;
#define FALSE 0
#define TRUE 1
#define INVALID_HANDLE_VALUE ((HANDLE)-1)
#define INVALID_FILE_ATTRIBUTES ((DWORD)-1)
#define FILE_ATTRIBUTE_NORMAL 0x80
#define FILE_ATTRIBUTE_DIRECTORY 0x10
#define GENERIC_WRITE 2
#define GENERIC_READ 1
#define FILE_SHARE_READ 1
#define OPEN_EXISTING 3
#define CREATE_ALWAYS 2
#define MOVEFILE_REPLACE_EXISTING 1
#define MOVEFILE_WRITE_THROUGH 8
#define ERROR_SUCCESS 0
#define ERROR_GEN_FAILURE 31
#define ERROR_WRITE_FAULT 29
#define ERROR_CANCELLED 1223
#define ERROR_FILE_NOT_FOUND 2
#define ERROR_ALREADY_EXISTS 183
#define ERROR_INVALID_DATA 13
#define ERROR_INVALID_HANDLE 6
#define ERROR_PROC_NOT_FOUND 127
#define ERROR_BAD_EXE_FORMAT 193
#define SCS_64BIT_BINARY 6
#define WAIT_OBJECT_0 0
#define WAIT_TIMEOUT 258
static DWORD GetLastError(void);
static void OutputDebugStringA(const char *);
static HANDLE CreateFileW(const WCHAR *,DWORD,DWORD,void *,DWORD,DWORD,HANDLE);
static BOOL WriteFile(HANDLE,const void *,DWORD,DWORD *,void *);
static BOOL FlushFileBuffers(HANDLE);
static BOOL CloseHandle(HANDLE);
static BOOL DeleteFileW(const WCHAR *);
static BOOL MoveFileExW(const WCHAR *,const WCHAR *,DWORD);
static DWORD GetFileAttributesW(const WCHAR *);
static DWORD WaitForSingleObject(HANDLE,DWORD);
static BOOL GetExitCodeProcess(HANDLE,DWORD *);
static BOOL TerminateProcess(HANDLE,DWORD);
static BOOL CreateProcessW(const WCHAR *,WCHAR *,void *,void *,BOOL,DWORD,void *,const WCHAR *,STARTUPINFOW *,PROCESS_INFORMATION *);
static BOOL CreateDirectoryW(const WCHAR *,void *);
static BOOL CopyFileW(const WCHAR *,const WCHAR *,BOOL);
static BOOL ReadFile(HANDLE,void *,DWORD,DWORD *,void *);
static HMODULE LoadLibraryW(const WCHAR *);
static FARPROC GetProcAddress(HMODULE,const char *);
static DWORD GetCurrentThreadId(void);
static BOOL Wow64DisableWow64FsRedirection(void **);
static BOOL Wow64RevertWow64FsRedirection(void *);
static BOOL GetBinaryTypeW(const WCHAR *,DWORD *);
'''
HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define MADEIRA_BOOTSTRAP_HOST_TEST 1
#include "BOOTSTRAP"
enum { OK, SETUP_CREATE_FAIL, SETUP_EXIT_FAIL, CLIENT_MISSING, CLIENT_CREATE_FAIL,
       CANCEL_BEFORE, CANCEL_DURING, WRITE_FAIL, MOVE_FAIL, DIRECTORY_FAIL, VDF_COPY_FAIL, EXISTING_DIRS, CANCEL_AFTER_REGISTER,
       COMMAND_MISSING, COMMAND_READ_FAIL, COMMAND_TRUNCATED,
       USER_LOAD_FAIL, GUI_API_MISSING, STATION_MISSING, DESKTOP_MISSING,
       REDIRECT_DISABLE_FAIL, REDIRECT_RESTORE_FAIL, DESKTOP_EXIT_FAIL,
       CLIENT64_MISSING, CLIENT64_WRONG_ARCH, CLIENT64_BACKUP_FAIL, CLIENT64_COPY_FAIL,
       CLIENT64_COPIED_WRONG_ARCH, CLIENT64_ACTIVATE_FAIL };
static int scenario, launches, installer_closed, cancelled_now, terminations, closes, copies;
static int binary_copies,client64_activated;
static int gui_loaded,station_retained,desktop_retained,redirection_disabled,redirect_calls,restore_calls;
static char written_text[160],stages[512];
static DWORD GetLastError(void){return scenario==EXISTING_DIRS?ERROR_ALREADY_EXISTS:redirection_disabled?87:5;}
static void OutputDebugStringA(const char *s){(void)s;}
static HANDLE CreateFileW(const WCHAR *p,DWORD a,DWORD b,void *c,DWORD d,DWORD e,HANDLE f){
    if(p==desktop_command_path){
        assert(installer_closed&&client64_activated&&copies==2&&a==GENERIC_READ&&b==FILE_SHARE_READ&&!c&&d==OPEN_EXISTING&&e==FILE_ATTRIBUTE_NORMAL&&!f);
        return scenario==COMMAND_MISSING?INVALID_HANDLE_VALUE:20;
    }
    assert(p==temp_path);(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;
    return scenario==WRITE_FAIL?INVALID_HANDLE_VALUE:10;
}
static BOOL WriteFile(HANDLE h,const void *p,DWORD n,DWORD *written,void *overlap){
    assert(h==10&&n<160&&!overlap);memcpy(written_text,p,n);written_text[n]=0;*written=n;return TRUE;
}
static BOOL FlushFileBuffers(HANDLE h){assert(h==10);return TRUE;}
static BOOL CloseHandle(HANDLE h){assert(h);if(h==1)installer_closed=1;closes++;return TRUE;}
static BOOL DeleteFileW(const WCHAR *p){assert(p==temp_path);return TRUE;}
static BOOL MoveFileExW(const WCHAR *from,const WCHAR *to,DWORD flags){
    if(from==client64_temp){
        assert(to==client_path&&binary_copies==2&&!client64_activated&&flags==(MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH));
        if(scenario==CLIENT64_ACTIVATE_FAIL)return FALSE;
        client64_activated=1;return TRUE;
    }
    assert(from==temp_path&&to==state_path&&flags==(MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH));
    if(scenario==MOVE_FAIL)return FALSE;
    strcat(stages,written_text);return TRUE;
}
static DWORD GetFileAttributesW(const WCHAR *p){
    if(p==cancel_path)return scenario==CANCEL_BEFORE||cancelled_now?0:INVALID_FILE_ATTRIBUTES;
    assert(p==client_path&&installer_closed);return scenario==CLIENT_MISSING?INVALID_FILE_ATTRIBUTES:0;
}
static DWORD WaitForSingleObject(HANDLE h,DWORD ms){
    assert(h==1||h==2);assert(ms==500||ms==5000);
    if(scenario==CANCEL_DURING&&h==1&&!terminations){cancelled_now=1;return WAIT_TIMEOUT;}
    return WAIT_OBJECT_0;
}
static BOOL GetExitCodeProcess(HANDLE h,DWORD *code){assert(h==1||h==2);*code=h==1&&scenario==SETUP_EXIT_FAIL?7:h==2&&scenario==DESKTOP_EXIT_FAIL?1:0;return TRUE;}
static BOOL TerminateProcess(HANDLE h,DWORD code){assert(h==1||h==2);assert(code==ERROR_CANCELLED||code==ERROR_WRITE_FAULT||code==87);terminations++;return TRUE;}
static BOOL CreateProcessW(const WCHAR *path,WCHAR *cmd,void *a,void *b,BOOL inherit,DWORD flags,void *env,const WCHAR *dir,STARTUPINFOW *s,PROCESS_INFORMATION *p){
    (void)a;(void)b;assert(!inherit&&!flags&&!env&&s->cb==sizeof(*s));assert(cmd&&cmd[0]=='"');
    if(path==setup_path){
        assert(launches==0&&!installer_closed&&!dir&&gui_loaded&&station_retained&&desktop_retained&&!redirection_disabled);
        if(scenario==SETUP_CREATE_FAIL)return FALSE;
        p->hProcess=1;p->hThread=101;
    }else{
        assert(path==desktop_path&&launches==1&&installer_closed&&client64_activated&&dir==client_dir&&copies==2&&redirection_disabled);
        if(scenario==CLIENT_CREATE_FAIL)return FALSE;
        p->hProcess=2;p->hThread=102;
    }
    launches++;return TRUE;
}
static BOOL CreateDirectoryW(const WCHAR *path,void *security){
    assert(installer_closed&&launches==1&&!security&&(path==config_dir||path==apps_dir));
    return scenario!=DIRECTORY_FAIL&&scenario!=EXISTING_DIRS;
}
static BOOL CopyFileW(const WCHAR *from,const WCHAR *to,BOOL fail_exists){
    assert(installer_closed&&launches==1&&!fail_exists);
    if(from==client_path){
        assert(to==client32_backup&&binary_copies==0&&!client64_activated);
        if(scenario==CLIENT64_BACKUP_FAIL)return FALSE;
        binary_copies++;return TRUE;
    }
    if(from==client64_stage){
        assert(to==client64_temp&&binary_copies==1&&!client64_activated);
        if(scenario==CLIENT64_COPY_FAIL)return FALSE;
        binary_copies++;return TRUE;
    }
    assert(client64_activated);
    assert((copies==0&&from==config_stage&&to==config_vdf)||(copies==1&&from==apps_stage&&to==apps_vdf));
    if(scenario==VDF_COPY_FAIL)return FALSE;
    copies++;
    if(scenario==CANCEL_AFTER_REGISTER&&copies==2)cancelled_now=1;
    return TRUE;
}
static BOOL GetBinaryTypeW(const WCHAR *path,DWORD *type){
    assert(installer_closed&&launches==1&&(path==client64_stage||path==client64_temp));
    if(path==client64_stage&&scenario==CLIENT64_MISSING)return FALSE;
    if(path==client64_temp)assert(binary_copies==2);
    *type=(scenario==CLIENT64_WRONG_ARCH&&path==client64_stage)||
          (scenario==CLIENT64_COPIED_WRONG_ARCH&&path==client64_temp)?0:SCS_64BIT_BINARY;
    return TRUE;
}
static BOOL ReadFile(HANDLE file,void *out,DWORD capacity,DWORD *read,void *overlap){
    static const WCHAR command[]=L"\"C:\\windows\\system32\\explorer.exe\" /desktop=shell,1280x720 cmd /c \"C:\\madeira-games\\fixture.bat\"";
    assert(file==20&&capacity>=sizeof(command)&&!overlap);
    if(scenario==COMMAND_READ_FAIL)return FALSE;
    memcpy(out,command,sizeof(command));*read=sizeof(command)-(scenario==COMMAND_TRUNCATED?2:0);
    return TRUE;
}
static HMODULE LoadLibraryW(const WCHAR *name){
    static const WCHAR expected[]=L"user32.dll";
    assert(!launches&&!memcmp(name,expected,sizeof(expected)));
    if(scenario==USER_LOAD_FAIL)return 0;
    gui_loaded=1;return 30;
}
static HWINSTA station(void){station_retained=scenario!=STATION_MISSING;return station_retained?31:0;}
static HDESK desktop(DWORD tid){assert(tid==24);desktop_retained=scenario!=DESKTOP_MISSING;return desktop_retained?32:0;}
static FARPROC GetProcAddress(HMODULE module,const char *name){
    assert(module==30);
    if(scenario==GUI_API_MISSING)return NULL;
    if(!strcmp(name,"GetProcessWindowStation"))return (FARPROC)station;
    assert(!strcmp(name,"GetThreadDesktop"));return (FARPROC)desktop;
}
static DWORD GetCurrentThreadId(void){return 24;}
static BOOL Wow64DisableWow64FsRedirection(void **previous){
    assert(installer_closed&&launches==1&&!redirection_disabled);redirect_calls++;
    if(scenario==REDIRECT_DISABLE_FAIL)return FALSE;
    *previous=(void *)(uintptr_t)0x1234;redirection_disabled=1;return TRUE;
}
static BOOL Wow64RevertWow64FsRedirection(void *previous){
    assert(previous==(void *)(uintptr_t)0x1234&&redirection_disabled);restore_calls++;
    if(scenario==REDIRECT_RESTORE_FAIL)return FALSE;
    redirection_disabled=0;return TRUE;
}
int main(void){
    for(scenario=OK;scenario<=CLIENT64_ACTIVATE_FAIL;scenario++){
        launches=installer_closed=cancelled_now=terminations=closes=copies=0;written_text[0]=stages[0]=0;
        gui_loaded=station_retained=desktop_retained=redirection_disabled=redirect_calls=restore_calls=0;
        binary_copies=client64_activated=0;
        DWORD code=bootstrap_run();
        if(scenario==OK||scenario==EXISTING_DIRS){
            assert(!code&&launches==2&&installer_closed&&closes==9&&!redirection_disabled);
            assert(binary_copies==2&&client64_activated);
            assert(redirect_calls==1&&restore_calls==1);
            const char *a=strstr(stages,"stage=installer"),*b=strstr(stages,"stage=checking"),*c=strstr(stages,"stage=starting"),*d=strstr(stages,"stage=waiting");
            assert(a&&b&&c&&d&&a<b&&b<c&&c<d);
        }else{
            assert(code);
            if(scenario==REDIRECT_RESTORE_FAIL||scenario==DESKTOP_EXIT_FAIL)assert(launches==2);
            else assert(launches<2);
            if(scenario==CLIENT_CREATE_FAIL)assert(restore_calls==1&&!redirection_disabled&&code==87);
            if(scenario==REDIRECT_DISABLE_FAIL)assert(redirect_calls==1&&!restore_calls);
            if(scenario==REDIRECT_RESTORE_FAIL)assert(terminations==1&&restore_calls==1&&code==87);
            if(scenario==DESKTOP_EXIT_FAIL)assert(code==1&&!redirection_disabled);
            if(scenario>=CLIENT64_MISSING){assert(!client64_activated&&!copies&&!redirect_calls);}
            if(scenario==CLIENT64_WRONG_ARCH||scenario==CLIENT64_COPIED_WRONG_ARCH)assert(code==ERROR_BAD_EXE_FORMAT);
            if(scenario==USER_LOAD_FAIL||scenario==GUI_API_MISSING||scenario==STATION_MISSING||scenario==DESKTOP_MISSING)assert(!launches&&!redirect_calls);
            if(scenario==CANCEL_DURING)assert(terminations==1&&installer_closed);
            if(scenario!=WRITE_FAIL&&scenario!=MOVE_FAIL)assert(strstr(stages,"stage=failed"));
        }
    }
    puts("PASS: controller retains GUI context before NSIS, starts native explorer with scoped WOW64 redirection, restores it on failure and reports nonzero desktop exits; install/register/cancel failure paths retained");
}
'''
with tempfile.TemporaryDirectory(prefix='mdeck-preparation-') as tmp:
    folder=Path(tmp)
    (folder/'windows.h').write_text(HEADER)
    (folder/'check.c').write_text(HARNESS.replace('#include "BOOTSTRAP"','#include "'+str(ROOT/'build/steam-bootstrap/bootstrap.c')+'"'))
    binary=folder/'check'
    subprocess.run(['xcrun','clang','-std=gnu11','-fshort-wchar','-Wall','-Wextra','-Werror',
                    '-I',str(folder),str(folder/'check.c'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
    native=(ROOT/'app/Madeira/Winios/Winios.m').read_text()
    snapshot=native[native.index('static pthread_mutex_t steam_setup_progress_lock'):native.index('/* csops syscall')]
    bridge=folder/'progress.c'
    bridge.write_text('#include <assert.h>\n#include <pthread.h>\n'
        'struct winios_steam_setup_progress { int step,percent,blocked; };\n'+snapshot+r'''
int main(void) {
    struct winios_steam_setup_progress value;
    winios_steam_setup_reset();
    winios_steam_setup_note(4,-1,4);winios_steam_setup_snapshot(&value);
    assert(value.step==4&&value.percent==-1&&value.blocked==4);
    winios_steam_setup_note(4,50,5);winios_steam_setup_snapshot(&value);
    assert(value.blocked==4&&value.percent==-1);
    winios_steam_setup_reset();winios_steam_setup_snapshot(&value);
    assert(value.step==0&&value.percent==-1&&value.blocked==0);
}
''')
    bridge_binary=folder/'progress'
    subprocess.run(['xcrun','clang','-std=c11','-Wall','-Wextra','-Werror','-pthread',str(bridge),'-o',str(bridge_binary)],check=True)
    subprocess.run([str(bridge_binary)],check=True)
    print('PASS: production native progress bridge transmits modal block 4 and rejects unknown codes')
print('Host control-flow test with fake Win32 processes; no real Wine/Steam or IPA execution.')
