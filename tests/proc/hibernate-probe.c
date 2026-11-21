/* A black-box checkpoint workload. Both processes keep their state in RAM.
 * The worker sleeps on an event and the parent sleeps in its window loop.
 * A fresh launch changes the session identifier and resets both counters. */
#include "hibernate-probe.h"
#include <limits.h>
#include <stdio.h>
#include <wchar.h>

enum { BUTTON_ID = 100 };

static struct shared_state *shared;
static HANDLE request, worker;
static HWND button, status;
static LONG displayed;
static BOOL pending, selftest;
static int result = 1;

static void update_count(void)
{
    wchar_t text[80];
    swprintf(text, ARRAYSIZE(text), L"Session %016llX  |  Count %ld", shared->session, displayed);
    SetWindowTextW(status, text);
}

static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wp, LPARAM lp)
{
    switch (message) {
    case WM_COMMAND:
        if (LOWORD(wp) == BUTTON_ID && HIWORD(wp) == BN_CLICKED && !pending) {
            pending = TRUE;
            EnableWindow(button, FALSE);
            if (!SetEvent(request)) DestroyWindow(window);
        }
        return 0;
    case WORKER_REPLY:
        if (!pending || displayed == LONG_MAX || wp != (WPARAM)(displayed + 1) ||
            InterlockedCompareExchange(&shared->completed, 0, 0) != (LONG)wp) {
            DestroyWindow(window);
            return 0;
        }
        pending = FALSE;
        displayed++;
        update_count();
        EnableWindow(button, TRUE);
        if (selftest) {
            if (displayed == 8) {
                result = 0;
                DestroyWindow(window);
            } else {
                PostMessageW(window, WM_COMMAND, BUTTON_ID, 0);
            }
        }
        return 0;
    case WM_CLOSE:
        result = selftest ? 1 : 0;
        DestroyWindow(window);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(result);
        return 0;
    default:
        return DefWindowProcW(window, message, wp, lp);
    }
}

int wmain(int argc, wchar_t **argv)
{
    selftest = argc == 2 && !wcscmp(argv[1], L"--selftest");
    if (argc != 1 && !selftest) return 1;

    FILETIME time;
    GetSystemTimeAsFileTime(&time);
    DWORD pid = GetCurrentProcessId();
    ULONGLONG session = (((ULONGLONG)time.dwHighDateTime << 32) | time.dwLowDateTime) ^ pid;
    wchar_t map_name[80], event_name[80];
    swprintf(map_name, 80, L"Local\\mdeck-probe-%016llX-page", session);
    swprintf(event_name, 80, L"Local\\mdeck-probe-%016llX-event", session);
    HANDLE mapping = CreateFileMappingW(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE,
                                        0, sizeof(*shared), map_name);
    if (!mapping || GetLastError() == ERROR_ALREADY_EXISTS) return 2;
    request = CreateEventW(NULL, FALSE, FALSE, event_name);
    if (!request || GetLastError() == ERROR_ALREADY_EXISTS) return 2;
    shared = MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(*shared));
    if (!shared) return 3;
    shared->session = session;

    HINSTANCE module = GetModuleHandleW(NULL);
    WNDCLASSW cls = { .lpfnWndProc = window_proc, .hInstance = module,
                      .lpszClassName = L"MDeckCheckpointProbe", .hCursor = LoadCursorW(NULL, IDC_ARROW),
                      .hbrBackground = (HBRUSH)(COLOR_WINDOW + 1) };
    if (!RegisterClassW(&cls)) return 4;
    HWND window = CreateWindowW(cls.lpszClassName, L"mdeck checkpoint test", WS_OVERLAPPEDWINDOW,
                                CW_USEDEFAULT, CW_USEDEFAULT, 520, 185, NULL, NULL, module, NULL);
    if (!window) return 4;
    shared->window = window;
    status = CreateWindowW(L"STATIC", L"", WS_VISIBLE | WS_CHILD | SS_LEFT,
                           16, 16, 460, 24, window, NULL, module, NULL);
    button = CreateWindowW(L"BUTTON", L"+1", WS_VISIBLE | WS_CHILD | WS_TABSTOP | BS_PUSHBUTTON,
                           16, 52, 160, 64, window, (HMENU)(UINT_PTR)BUTTON_ID, module, NULL);
    if (!status || !button) return 4;

    const wchar_t worker_name[] = L"hibernate-worker.exe";
    wchar_t path[MAX_PATH], command[2 * MAX_PATH];
    DWORD len = GetModuleFileNameW(NULL, path, ARRAYSIZE(path));
    if (!len || len >= ARRAYSIZE(path)) return 5;
    wchar_t *separator = wcsrchr(path, L'\\');
    if (!separator) return 5;
    wchar_t *filename = separator + 1;
    if ((size_t)(filename - path) + ARRAYSIZE(worker_name) > ARRAYSIZE(path)) return 5;
    wmemcpy(filename, worker_name, ARRAYSIZE(worker_name));
    if (swprintf(command, ARRAYSIZE(command), L"\"%ls\" %lu %ls %ls",
                 path, pid, map_name, event_name) < 0) return 5;
    STARTUPINFOW startup = { .cb = sizeof(startup) };
    PROCESS_INFORMATION child;
    if (!CreateProcessW(path, command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &child)) return 5;
    CloseHandle(child.hThread);
    worker = child.hProcess;
    update_count();
    ShowWindow(window, SW_SHOW);
    if (selftest) PostMessageW(window, WM_COMMAND, BUTTON_ID, 0);

    for (;;) {
        DWORD wake = MsgWaitForMultipleObjects(1, &worker, FALSE, selftest ? 15000 : INFINITE, QS_ALLINPUT);
        if (wake != WAIT_OBJECT_0 + 1) return 6;
        MSG msg;
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) return (int)msg.wParam;
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}
