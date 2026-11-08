#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <wctype.h>
typedef wchar_t WCHAR;
typedef const WCHAR *LPCWSTR;
typedef void *HICON, *HANDLE, *HWND, *LPVOID;
typedef unsigned int DWORD, UINT;
typedef int BOOL, HRESULT, IShellLinkW;
typedef struct { HANDLE hEvent; } OVERLAPPED;
typedef struct { DWORD NextEntryOffset, Action, FileNameLength; WCHAR FileName[40]; } FILE_NOTIFY_INFORMATION;
#define CALLBACK
#define TRUE 1
#define FALSE 0
#define SUCCEEDED(r) ((r)>=0)
#define WARN(...) ((void)0)
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define FILE_ACTION_ADDED 1
#define FILE_ACTION_REMOVED 2
#define FILE_ACTION_MODIFIED 3
#define FILE_ACTION_RENAMED_OLD_NAME 4
#define FILE_ACTION_RENAMED_NEW_NAME 5
#define FILE_LIST_DIRECTORY 1
#define SYNCHRONIZE 2
#define FILE_SHARE_READ 4
#define FILE_SHARE_WRITE 8
#define OPEN_EXISTING 3
#define FILE_FLAG_BACKUP_SEMANTICS 16
#define FILE_FLAG_OVERLAPPED 32
#define FILE_NOTIFY_CHANGE_FILE_NAME 1
#define FILE_NOTIFY_CHANGE_LAST_WRITE 16
#define WAIT_OBJECT_0 0
#define INFINITE ((DWORD)-1)
#define ERROR_OUTOFMEMORY 14
#define IDI_APPLICATION 32512
struct launcher { WCHAR *path; HICON icon; WCHAR *title; };
static struct launcher **launchers;
static unsigned int nb_launchers, nb_allocated;
static WCHAR *desktop_folder=L"user", *desktop_folder_public=L"public";
static int destroys, generic_icons, releases;
static int wcsicmp(const WCHAR *a,const WCHAR *b) {
    while(*a && towlower(*a)==towlower(*b)) { a++;b++; } return towlower(*a)-towlower(*b);
}
static WCHAR *append_path(const WCHAR *folder,const WCHAR *filename,int len) {
    if(len<0) len=(int)wcslen(filename);
    size_t base=wcslen(folder);WCHAR *path=calloc(base+len+2,sizeof(WCHAR));assert(path);
    wmemcpy(path,folder,base);path[base]='/';wmemcpy(path+base+1,filename,len);return path;
}
static IShellLinkW *load_shelllink(const WCHAR *path) {
    static IShellLinkW link;
    return wcsstr(path,L".lnk") ? &link : NULL;
}
static HICON extract_icon(IShellLinkW *link) { assert(link);return NULL; }
static HICON LoadIconW(HANDLE module,LPCWSTR icon) {
    assert(!module && (uintptr_t)icon==IDI_APPLICATION);generic_icons++;return (HICON)1;
}
static HICON CopyIcon(HICON icon) { assert(icon);return icon; }
static BOOL DestroyIcon(HICON icon) { if(icon) destroys++;return TRUE; }
static WCHAR *build_title(const WCHAR *filename,int len) {
    if(len<0)len=(int)wcslen(filename);WCHAR *p=calloc(len+1,sizeof(WCHAR));assert(p);wmemcpy(p,filename,len);return p;
}
static void IShellLinkW_Release(IShellLinkW *link) { assert(link);releases++; }
static void free_launcher(struct launcher *launcher);
/* PRODUCTION_LAUNCHERS */

/* These fakes reject a second outstanding request on the same OVERLAPPED.
 * The unpatched watcher rearms both directories even if only one completed. */
static int armed[3], waits, overlaps, last_error, events_created;
static char *buffers[3];
static HRESULT CoInitialize(void *ignored) { (void)ignored;return 0; }
static void CoUninitialize(void) {}
static HANDLE CreateFileW(const WCHAR *name,DWORD access,DWORD share,void *security,DWORD creation,DWORD flags,HANDLE template) {
    (void)access;(void)share;(void)security;(void)creation;(void)flags;(void)template;
    return (HANDLE)(uintptr_t)(wcscmp(name,desktop_folder) ? 2 : 1);
}
static HANDLE CreateEventW(void *security,BOOL manual,BOOL initial,const WCHAR *name) {
    (void)security;assert(!manual&&!initial&&!name);return (HANDLE)(uintptr_t)(10+ ++events_created);
}
static DWORD GetLastError(void) { return last_error; }
static BOOL ReadDirectoryChangesW(HANDLE handle,char *buf,DWORD size,BOOL subtree,DWORD filter,DWORD *count,OVERLAPPED *overlapped,void *callback) {
    unsigned n=(unsigned)(uintptr_t)handle;assert(n==1||n==2);assert(size==4096&&!subtree&&!count&&overlapped&&!callback);
    assert(filter & FILE_NOTIFY_CHANGE_FILE_NAME);
    if(armed[n]) { overlaps++;last_error=170;return FALSE; }
    armed[n]=1;buffers[n]=buf;return TRUE;
}
static DWORD WaitForMultipleObjects(DWORD count,HANDLE *events,BOOL all,DWORD timeout) {
    assert(count==2&&events[0]&&events[1]&&!all&&timeout==INFINITE);
    if(waits++==3)return 99;return waits%2 ? WAIT_OBJECT_0 : WAIT_OBJECT_0+1;
}
static BOOL GetOverlappedResult(HANDLE handle,OVERLAPPED *overlapped,DWORD *count,BOOL wait) {
    unsigned n=(unsigned)(uintptr_t)handle;assert(n==1||n==2);assert(armed[n]&&overlapped&&!wait);armed[n]=0;
    FILE_NOTIFY_INFORMATION *info=(void *)buffers[n];memset(info,0,sizeof(*info));
    info->Action=FILE_ACTION_ADDED;wcscpy(info->FileName,L"fresh.lnk");info->FileNameLength=(DWORD)(wcslen(info->FileName)*sizeof(WCHAR));
    *count=sizeof(*info);return TRUE;
}
static BOOL InvalidateRect(HWND hwnd,void *rect,BOOL erase) { assert(hwnd&&!rect&&erase);return TRUE; }
static BOOL CloseHandle(HANDLE h) { (void)h;return TRUE; }
/* PRODUCTION_WATCHER */
int main(void) {
    nb_allocated=2;launchers=calloc(nb_allocated,sizeof(*launchers));assert(launchers);
    assert(add_launcher(desktop_folder,L"App.lnk",-1) && nb_launchers==1 && generic_icons==1);
    assert(add_launcher(desktop_folder,L"App.lnk",-1) && nb_launchers==1 && destroys==1);
    FILE_NOTIFY_INFORMATION modified={0};modified.Action=FILE_ACTION_MODIFIED;wcscpy(modified.FileName,L"App.lnk");
    modified.FileNameLength=(DWORD)(wcslen(modified.FileName)*sizeof(WCHAR));
    assert(process_changes(desktop_folder,(char *)&modified) && nb_launchers==1 && destroys==2);
    assert(!add_launcher(desktop_folder,L"not-a-link.txt",-1) && nb_launchers==1);
    (void)watch_desktop_folders((void *)9);
    if(overlaps || waits!=4) return 1;
    assert(nb_launchers==3 && releases==6);
    while(nb_launchers) free_launcher(launchers[--nb_launchers]);free(launchers);
    assert(generic_icons==destroys);return 0;
}
