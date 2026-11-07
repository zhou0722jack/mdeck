#!/usr/bin/env python3
"""Exercise Wine's real parent traversal and mouse activation on a detached desktop."""
from pathlib import Path
import importlib.util
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('prepare_window', ROOT / 'build/win32u-unix/prepare-window-source.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
source = (ROOT / 'wine/dlls/win32u/window.c').read_text()


def function(text, signature):
    start = text.index(signature)
    opening = text.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


message = (ROOT / 'build/win32u-unix/message_ios.c').read_text()
activation = message[message.index('        if (msg->hwnd != info.hwndActive)', message.index('static BOOL process_mouse_message(')):]
activation = activation[:activation.index('\n#ifdef WINE_IOS')]
harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
typedef uintptr_t HWND, HANDLE, WPARAM;
typedef intptr_t LPARAM;
typedef unsigned int UINT, DWORD, user_handle_t;
typedef int BOOL;
typedef struct { HWND parent; } WND;
#define WINAPI
#define WND_OTHER_PROCESS ((WND *)1)
#define WND_DESKTOP ((WND *)2)
#define NTUSER_OBJ_WINDOW 1
#define GA_PARENT 1
#define GA_ROOT 2
#define GA_ROOTOWNER 3
#define ERROR_INVALID_WINDOW_HANDLE 1400
#define GWL_STYLE (-16)
#define WS_CHILD 0x40000000u
#define WS_POPUP 0x80000000u
#define WM_MOUSEACTIVATE 0x21
#define MA_ACTIVATE 1
#define MA_ACTIVATEANDEAT 2
#define MA_NOACTIVATE 3
#define MA_NOACTIVATEANDEAT 4
#define WM_LBUTTONDOWN 0x201
#define MAKELONG(a,b) ((LPARAM)((unsigned)(a) | ((unsigned)(b) << 16)))
#define TRUE 1
#define FALSE 0
#define WARN(...) ((void)0)
static WND root={1}, button={2}, nested={3};
static int locks, foreign_desktop;
static HWND activated;
static void *get_user_handle_ptr(HANDLE h, unsigned short type) {
    assert(type == NTUSER_OBJ_WINDOW);
    /* Desktop belongs to this process on the server, but has no local WND. */
    if (h == 1) return foreign_desktop ? WND_OTHER_PROCESS : NULL;
    WND *w = h == 2 ? &root : h == 3 ? &button : h == 4 ? &nested : NULL;
    if (w) locks++;
    return w;
}
static BOOL is_desktop_window(HWND h) { assert(!locks); return h == 1 || h == 10; }
static void release_win_ptr(WND *w) { assert(w && w != WND_DESKTOP); assert(locks-- == 1); }
static HWND get_full_window_handle(HWND h) { return h; }
static void RtlSetLastWin32Error(UINT e) { assert(e == ERROR_INVALID_WINDOW_HANDLE); }
static HWND get_parent(HWND h) { return h == 3 ? 2 : 0; }
static user_handle_t *reply_data;
static size_t reply_capacity;
struct request { user_handle_t handle; };
struct reply { int count; user_handle_t parent; };
#define SERVER_START_REQ(n) do { struct request r={0}, *req=&r; struct reply q={0}, *reply=&q;
#define SERVER_END_REQ } while(0)
static void wine_server_set_reply(struct request *r, void *p, size_t n) { (void)r; reply_data=p; reply_capacity=n; }
static int wine_server_call(struct request *r) { (void)r; (void)reply_data; (void)reply_capacity; return 1; }
static int wine_server_call_err(struct request *r) { return wine_server_call(r); }
static user_handle_t wine_server_user_handle(HWND h) { return (user_handle_t)h; }
static HWND wine_server_ptr_handle(user_handle_t h) { return h; }
/* PRODUCTION */
static DWORD get_window_long(HWND h, int i) { assert(i == GWL_STYLE); return h == 3 || h == 4 ? WS_CHILD : 0; }
static UINT send_message(HWND h, UINT m, WPARAM wp, LPARAM lp) {
    assert(h == 3 || h == 4); assert(m == WM_MOUSEACTIVATE); (void)wp; (void)lp; return MA_ACTIVATE;
}
static BOOL set_foreground_window(HWND h, BOOL mouse, BOOL internal) {
    assert(mouse && !internal); activated=h; return h == 2;
}
static BOOL click(HWND hwnd) {
    struct { HWND hwnd, hwndActive; UINT message; } state={hwnd,0,WM_LBUTTONDOWN}, *msg=&state, info={0};
    int hittest=1; BOOL eat_msg=FALSE;
    /* ACTIVATION */
    return !eat_msg && activated == 2;
}
int main(void) {
    if (!click(3)) return 1;
    assert(NtUserGetAncestor(3,GA_ROOT) == 2);
    assert(NtUserGetAncestor(4,GA_ROOT) == 2 && click(4));
    assert(NtUserGetAncestor(2,GA_ROOT) == 2);
    assert(NtUserGetAncestor(3,GA_PARENT) == 2);
    assert(NtUserGetAncestor(3,GA_ROOTOWNER) == 2);
    assert(NtUserGetAncestor(99,GA_ROOT) == 0);
    assert(get_win_ptr(10) == WND_DESKTOP);
    foreign_desktop=1;
    assert(NtUserGetAncestor(3,GA_ROOT) == 2 && click(3));
    assert(!locks);
    return 0;
}
'''
build = (ROOT / 'build/win32u-unix/build.sh').read_text()
assert 'prepare-window-source.py' in build and 'compile_one "$OBJ_DIR/window_ios.c" "window"' in build
fixed = adapter.prepare(source)
try:
    adapter.prepare(source.replace('NTUSER_OBJ_WINDOW )) == WND_OTHER_PROCESS)', 'changed_signature'))
except ValueError:
    pass
else:
    raise AssertionError('Wine source drift must fail the build')
with tempfile.TemporaryDirectory(prefix='madeira-button-') as tmp:
    for label, text in [('fixed', fixed), ('original', source)]:
        functions = '\n'.join(function(text, signature) for signature in [
            'WND *get_win_ptr( HWND hwnd )', 'static HWND *list_window_parents( HWND hwnd )',
            'HWND WINAPI NtUserGetAncestor( HWND hwnd, UINT type )'])
        path = Path(tmp) / f'{label}.c'
        path.write_text(harness.replace('/* PRODUCTION */', functions).replace('/* ACTIVATION */', activation))
        binary = path.with_suffix('')
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', str(path), '-o', str(binary)], check=True)
        result = subprocess.run([str(binary)])
        assert result.returncode == (0 if label == 'fixed' else 1), label
print('PASS: detached desktop, nested button activation, parent/root-owner, invalid handles and balanced locks')
print('PASS: original Wine path reproduces the dropped press; source drift is rejected')
