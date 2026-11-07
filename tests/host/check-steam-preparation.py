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
#define CREATE_ALWAYS 2
#define MOVEFILE_REPLACE_EXISTING 1
#define MOVEFILE_WRITE_THROUGH 8
#define ERROR_SUCCESS 0
#define ERROR_GEN_FAILURE 31
#define ERROR_WRITE_FAULT 29
#define ERROR_CANCELLED 1223
#define ERROR_FILE_NOT_FOUND 2
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
'''
HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define MADEIRA_BOOTSTRAP_HOST_TEST 1
#include "BOOTSTRAP"
enum { OK, SETUP_CREATE_FAIL, SETUP_EXIT_FAIL, CLIENT_MISSING, CLIENT_CREATE_FAIL,
       CANCEL_BEFORE, CANCEL_DURING, WRITE_FAIL, MOVE_FAIL };
static int scenario, launches, installer_closed, cancelled_now, terminations, closes;
static char written_text[160],stages[512];
static DWORD GetLastError(void){return 5;}
static void OutputDebugStringA(const char *s){(void)s;}
static HANDLE CreateFileW(const WCHAR *p,DWORD a,DWORD b,void *c,DWORD d,DWORD e,HANDLE f){
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
static BOOL GetExitCodeProcess(HANDLE h,DWORD *code){assert(h==1||h==2);*code=h==1&&scenario==SETUP_EXIT_FAIL?7:0;return TRUE;}
static BOOL TerminateProcess(HANDLE h,DWORD code){assert(h==1||h==2);assert(code==ERROR_CANCELLED||code==ERROR_WRITE_FAULT);terminations++;return TRUE;}
static BOOL CreateProcessW(const WCHAR *path,WCHAR *cmd,void *a,void *b,BOOL inherit,DWORD flags,void *env,const WCHAR *dir,STARTUPINFOW *s,PROCESS_INFORMATION *p){
    (void)a;(void)b;assert(!inherit&&!flags&&!env&&s->cb==sizeof(*s));assert(cmd&&cmd[0]=='"');
    if(path==setup_path){
        assert(launches==0&&!installer_closed&&!dir);
        if(scenario==SETUP_CREATE_FAIL)return FALSE;
        p->hProcess=1;p->hThread=101;
    }else{
        assert(path==client_path&&launches==1&&installer_closed&&dir==client_dir);
        if(scenario==CLIENT_CREATE_FAIL)return FALSE;
        p->hProcess=2;p->hThread=102;
    }
    launches++;return TRUE;
}
int main(void){
    for(scenario=OK;scenario<=MOVE_FAIL;scenario++){
        launches=installer_closed=cancelled_now=terminations=closes=0;written_text[0]=stages[0]=0;
        DWORD code=bootstrap_run();
        if(scenario==OK){
            assert(!code&&launches==2&&installer_closed&&closes==8);
            const char *a=strstr(stages,"stage=installer"),*b=strstr(stages,"stage=checking"),*c=strstr(stages,"stage=starting"),*d=strstr(stages,"stage=waiting");
            assert(a&&b&&c&&d&&a<b&&b<c&&c<d);
        }else{
            assert(code&&launches<2);
            if(scenario==CANCEL_DURING)assert(terminations==1&&installer_closed);
            if(scenario!=WRITE_FAIL&&scenario!=MOVE_FAIL)assert(strstr(stages,"stage=failed"));
        }
    }
    puts("PASS: production controller waits for installer exit, checks exact Steam path, starts one successor; setup/file/start/cancel/state-write failures block handoff");
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
print('Host control-flow test with fake Win32 processes; no real Wine/Steam or IPA execution.')
