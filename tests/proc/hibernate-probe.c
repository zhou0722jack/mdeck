/* Both processes keep their live state in RAM. A fresh launch resets it.
 * In checkpoint mode, Madeira can request a joint snapshot between clicks. */
#include "hibernate-probe.h"
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

enum { BUTTON_ID = 100, CHECKPOINT_TIMER = 101 };

static struct shared_state *shared;
static HANDLE request, worker;
static HWND button, status;
static LONG displayed;
static enum work_kind pending;
static BOOL ready, selftest;
static unsigned char capture_token[CHECKPOINT_TOKEN_SIZE];
static int result = 1;

static void update_count(void)
{
    wchar_t text[80];
    swprintf(text, ARRAYSIZE(text), L"Session %016llX  |  Count %ld", shared->session, displayed);
    SetWindowTextW(status, text);
}

static BOOL read_record(const wchar_t *path, void *record, DWORD length)
{
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE, NULL,
                              OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return FALSE;
    LARGE_INTEGER size;
    DWORD count;
    BOOL ok = GetFileSizeEx(file, &size) && size.QuadPart == length &&
              ReadFile(file, record, length, &count, NULL) && count == length;
    CloseHandle(file);
    return ok;
}

static void send_snapshot(LONG private_count)
{
    struct checkpoint_reply reply = {
        .state = {
            .session = shared->session,
            .displayed = displayed,
            .completed = InterlockedCompareExchange(&shared->completed, 0, 0),
            .worker = private_count,
            .version = CHECKPOINT_VERSION,
        },
    };
    memcpy(reply.token, capture_token, sizeof(reply.token));
    HANDLE file = CreateFileW(CHECKPOINT_REPLY_TEMP, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    DWORD count;
    BOOL written = WriteFile(file, &reply, sizeof(reply), &count, NULL) && count == sizeof(reply);
    CloseHandle(file);
    if (written) MoveFileExW(CHECKPOINT_REPLY_TEMP, CHECKPOINT_REPLY, MOVEFILE_REPLACE_EXISTING);
}

static void signal_worker(HWND window, enum work_kind work)
{
    pending = work;
    EnableWindow(button, FALSE);
    InterlockedExchange(&shared->operation, work);
    if (!SetEvent(request)) DestroyWindow(window);
}

static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wp, LPARAM lp)
{
    switch (message) {
    case WM_COMMAND:
        if (LOWORD(wp) == BUTTON_ID && HIWORD(wp) == BN_CLICKED && ready && pending == IDLE &&
            displayed < LONG_MAX)
            signal_worker(window, INCREMENT);
        return 0;
    case WM_TIMER: {
        unsigned char token[CHECKPOINT_TOKEN_SIZE];
        if (wp == CHECKPOINT_TIMER && ready && pending == IDLE &&
            read_record(CHECKPOINT_REQUEST, token, sizeof(token)) &&
            memcmp(token, capture_token, sizeof(token))) {
            memcpy(capture_token, token, sizeof(token));
            signal_worker(window, CAPTURE);
        }
        return 0;
    }
    case WORKER_READY:
        if (ready || wp != (WPARAM)displayed) {
            DestroyWindow(window);
            return 0;
        }
        ready = TRUE;
        update_count();
        ShowWindow(window, SW_SHOW);
        if (selftest) PostMessageW(window, WM_COMMAND, BUTTON_ID, 0);
        return 0;
    case WORKER_REPLY: {
        LONG expected = displayed + (pending == INCREMENT);
        if (pending == IDLE || lp != (LPARAM)pending || wp != (WPARAM)expected ||
            InterlockedCompareExchange(&shared->completed, 0, 0) != expected) {
            DestroyWindow(window);
            return 0;
        }
        if (pending == CAPTURE) send_snapshot((LONG)wp);
        else {
            displayed = expected;
            update_count();
        }
        pending = IDLE;
        EnableWindow(button, displayed < LONG_MAX);
        if (selftest) {
            if (displayed == 8) {
                result = 0;
                DestroyWindow(window);
            } else {
                PostMessageW(window, WM_COMMAND, BUTTON_ID, 0);
            }
        }
        return 0;
    }
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
    BOOL restoring = argc == 2 && !wcscmp(argv[1], L"--restore");
    BOOL checkpoint = restoring || (argc == 2 && !wcscmp(argv[1], L"--checkpoint"));
    if (argc != 1 && !selftest && !checkpoint) return 1;

    FILETIME time;
    GetSystemTimeAsFileTime(&time);
    DWORD pid = GetCurrentProcessId();
    ULONGLONG session = (((ULONGLONG)time.dwHighDateTime << 32) | time.dwLowDateTime) ^ pid;
    struct checkpoint_state restored = {0};
    if (restoring) {
        if (!read_record(CHECKPOINT_RESTORE, &restored, sizeof(restored)) ||
            restored.version != CHECKPOINT_VERSION || !restored.session || restored.displayed < 0 ||
            restored.displayed != restored.completed || restored.displayed != restored.worker)
            return 7;
        session = restored.session;
        displayed = restored.displayed;
    }
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
    shared->completed = restored.completed;
    shared->initial_worker = restored.worker;

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
    if (checkpoint && !SetTimer(window, CHECKPOINT_TIMER, 250, NULL)) return 4;

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
