/* SPDX-License-Identifier: GPL-3.0-or-later
 * Keeps one Wine session alive across setup -> client. No CRT or UI. */
#include <windows.h>

#ifndef MADEIRA_BOOTSTRAP_HOST_TEST
/* Clang can lower local UTF-16 array initialization to memcpy even with
 * -fno-builtin. Keep this one freestanding helper instead of importing CRT. */
void *__cdecl memcpy(void *out, const void *in, size_t length) {
    unsigned char *to = out;
    const unsigned char *from = in;
    for (size_t i = 0; i < length; i++) to[i] = from[i];
    return out;
}
#endif

static const WCHAR setup_path[] = L"C:\\Madeira\\Installers\\SteamSetup.exe";
static const WCHAR client_path[] = L"C:\\Program Files\\Steam Client\\Steam.exe";
static const WCHAR client_dir[] = L"C:\\Program Files\\Steam Client";
static const WCHAR client64_stage[] = L"C:\\Madeira\\Installers\\Steam64.exe";
static const WCHAR client64_temp[] = L"C:\\Program Files\\Steam Client\\Steam64.tmp.exe";
static const WCHAR client32_backup[] = L"C:\\Madeira\\Installers\\Steam-before-win64-installed.exe";
static const WCHAR state_path[] = L"C:\\Madeira\\Installers\\SteamBootstrap.state";
static const WCHAR temp_path[] = L"C:\\Madeira\\Installers\\SteamBootstrap.state.tmp";
static const WCHAR cancel_path[] = L"C:\\Madeira\\Installers\\SteamBootstrap.cancel";
static const WCHAR config_dir[] = L"C:\\Program Files\\Steam Client\\config";
static const WCHAR apps_dir[] = L"C:\\Program Files\\Steam Client\\steamapps";
static const WCHAR config_stage[] = L"C:\\Madeira\\Installers\\SteamLibraries.config.vdf";
static const WCHAR apps_stage[] = L"C:\\Madeira\\Installers\\SteamLibraries.steamapps.vdf";
static const WCHAR config_vdf[] = L"C:\\Program Files\\Steam Client\\config\\libraryfolders.vdf";
static const WCHAR apps_vdf[] = L"C:\\Program Files\\Steam Client\\steamapps\\libraryfolders.vdf";
static const WCHAR desktop_path[] = L"C:\\windows\\system32\\explorer.exe";
static const WCHAR desktop_command_path[] = L"C:\\Madeira\\Installers\\SteamDesktop.command";

static void zero_bytes(void *data, SIZE_T length) {
    unsigned char *p = data;
    while (length--) *p++ = 0;
}
static unsigned append(char *out, unsigned at, const char *value) {
    while (*value) out[at++] = *value++;
    return at;
}
static unsigned decimal(char *out, unsigned at, DWORD value) {
    char digits[10]; unsigned n = 0;
    do { digits[n++] = '0' + value % 10; value /= 10; } while (value);
    while (n) out[at++] = digits[--n];
    return at;
}
static BOOL report(const char *stage, DWORD error) {
    char text[160]; unsigned length = 0; DWORD written = 0;
    HANDLE file;
    length = append(text, length, "v1\nstage=");
    length = append(text, length, stage);
    length = append(text, length, "\nerror=");
    length = decimal(text, length, error);
    text[length++] = '\n'; text[length] = 0;
    OutputDebugStringA("[steam-bootstrap] state follows"); OutputDebugStringA(text);
    file = CreateFileW(temp_path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return FALSE;
    BOOL ok = WriteFile(file, text, length, &written, NULL) && written == length;
    if (ok) ok = FlushFileBuffers(file);
    CloseHandle(file);
    if (!ok) { DeleteFileW(temp_path); return FALSE; }
    return MoveFileExW(temp_path, state_path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
}
static DWORD failed(DWORD error) {
    if (!error) error = ERROR_GEN_FAILURE;
    report("failed", error);
    return error;
}
static BOOL cancelled(void) { return GetFileAttributesW(cancel_path) != INVALID_FILE_ATTRIBUTES; }
static DWORD wait_program(HANDLE process, DWORD *exit_code) {
    for (;;) {
        DWORD wait = WaitForSingleObject(process, 500);
        if (wait == WAIT_OBJECT_0) return GetExitCodeProcess(process, exit_code) ? ERROR_SUCCESS : GetLastError();
        if (wait != WAIT_TIMEOUT) return GetLastError();
        if (cancelled()) {
            if (!TerminateProcess(process, ERROR_CANCELLED)) return GetLastError();
            WaitForSingleObject(process, 5000);
            return ERROR_CANCELLED;
        }
    }
}
static BOOL start_program(const WCHAR *path, WCHAR *command, const WCHAR *directory, PROCESS_INFORMATION *process) {
    STARTUPINFOW startup;
    zero_bytes(&startup, sizeof(startup)); zero_bytes(process, sizeof(*process));
    startup.cb = sizeof(startup);
    return CreateProcessW(path, command, NULL, NULL, FALSE, 0, NULL, directory, &startup, process);
}

static DWORD prepare_gui_context(void) {
    typedef HWINSTA (WINAPI *get_station_fn)(void);
    typedef HDESK (WINAPI *get_desktop_fn)(DWORD);
    /* win32u's init_user is shared by the in-process Wine children. Load it
     * first in the long-lived controller, so its station/desktop survive NSIS.
     * Keep USER32 loaded until process exit; this creates no visible window. */
    HMODULE user = LoadLibraryW(L"user32.dll");
    if (!user) return GetLastError();
    get_station_fn station = (get_station_fn)GetProcAddress(user, "GetProcessWindowStation");
    get_desktop_fn desktop = (get_desktop_fn)GetProcAddress(user, "GetThreadDesktop");
    if (!station || !desktop) return ERROR_PROC_NOT_FOUND;
    if (!station() || !desktop(GetCurrentThreadId())) return ERROR_INVALID_HANDLE;
    OutputDebugStringA("[steam-bootstrap] controller GUI station and desktop retained");
    return ERROR_SUCCESS;
}

static DWORD start_desktop(WCHAR *command, PROCESS_INFORMATION *process) {
    void *previous;
    DWORD error;
    /* The controller is i386. Without this scope system32 is redirected to
     * syswow64, unlike the native explorer used by a regular Steam launch. */
    if (!Wow64DisableWow64FsRedirection(&previous)) return GetLastError();
    BOOL started = start_program(desktop_path, command, client_dir, process);
    error = started ? ERROR_SUCCESS : GetLastError();
    BOOL restored = Wow64RevertWow64FsRedirection(previous);
    if (!restored && !error) {
        error = GetLastError();
        TerminateProcess(process->hProcess, error);
        CloseHandle(process->hThread);
        CloseHandle(process->hProcess);
    }
    if (!restored) OutputDebugStringA("[steam-bootstrap] filesystem redirection restore failed");
    if (!error) OutputDebugStringA("[steam-bootstrap] native system32 explorer started; redirection restored");
    return error;
}

static DWORD register_libraries(void) {
    /* Do not populate the target before NSIS verifies that it is empty. */
    if (!CreateDirectoryW(config_dir, NULL) && GetLastError() != ERROR_ALREADY_EXISTS) return GetLastError();
    if (!CreateDirectoryW(apps_dir, NULL) && GetLastError() != ERROR_ALREADY_EXISTS) return GetLastError();
    if (!CopyFileW(config_stage, config_vdf, FALSE)) return GetLastError();
    if (!CopyFileW(apps_stage, apps_vdf, FALSE)) return GetLastError();
    OutputDebugStringA("[steam-bootstrap] libraries registered after installer exit");
    return ERROR_SUCCESS;
}

static DWORD read_desktop_command(WCHAR *command, DWORD capacity) {
    DWORD bytes = 0, error = 0;
    HANDLE file = CreateFileW(desktop_command_path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return GetLastError();
    BOOL ok = ReadFile(file, command, (capacity - 1) * sizeof(*command), &bytes, NULL);
    if (!ok) error = GetLastError();
    CloseHandle(file);
    if (error) return error;
    if (bytes < 2 * sizeof(*command) || bytes % sizeof(*command) ||
        command[0] != '"' || command[bytes / sizeof(*command) - 1] != 0) return ERROR_INVALID_DATA;
    return ERROR_SUCCESS;
}

/* The app verifies the staged image's pinned SHA-256 before this session.
 * Recheck its PE architecture and the copied image before atomic activation. */
static DWORD activate_client64(void) {
    DWORD type;
    if (!GetBinaryTypeW(client64_stage, &type)) return GetLastError();
    if (type != SCS_64BIT_BINARY) return ERROR_BAD_EXE_FORMAT;
    if (!CopyFileW(client_path, client32_backup, FALSE)) return GetLastError();
    if (!CopyFileW(client64_stage, client64_temp, FALSE)) return GetLastError();
    if (!GetBinaryTypeW(client64_temp, &type)) return GetLastError();
    if (type != SCS_64BIT_BINARY) return ERROR_BAD_EXE_FORMAT;
    if (!MoveFileExW(client64_temp, client_path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) return GetLastError();
    OutputDebugStringA("[steam-client64] verified x86_64 bootstrap activated after setup");
    return ERROR_SUCCESS;
}

static DWORD bootstrap_run(void) {
    PROCESS_INFORMATION process;
    DWORD error, code = 0, attributes;
    WCHAR setup_command[] = L"\"C:\\Madeira\\Installers\\SteamSetup.exe\" /D=C:\\Program Files\\Steam Client";
    /* The native steam.exe child rule appends SteamClient.clientArguments,
     * including sandbox/GPU compatibility, also on updater restarts. */
    WCHAR client_command[1024];
    if (cancelled()) return failed(ERROR_CANCELLED);
    error = prepare_gui_context();
    if (error) return failed(error);
    if (!report("installer", 0)) return failed(ERROR_WRITE_FAULT);
    if (!start_program(setup_path, setup_command, NULL, &process)) return failed(GetLastError());
    CloseHandle(process.hThread);
    error = wait_program(process.hProcess, &code);
    CloseHandle(process.hProcess);
    if (error) return failed(error);
    if (code) return failed(code);
    /* This is after the installer process exit, not after a button post. */
    if (!report("checking", 0)) return failed(ERROR_WRITE_FAULT);
    if (cancelled()) return failed(ERROR_CANCELLED);
    attributes = GetFileAttributesW(client_path);
    if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_DIRECTORY)) return failed(ERROR_FILE_NOT_FOUND);
    error = activate_client64();
    if (error) return failed(error);
    error = register_libraries();
    if (error) return failed(error);
    error = read_desktop_command(client_command, sizeof(client_command) / sizeof(*client_command));
    if (error) return failed(error);
    if (cancelled()) return failed(ERROR_CANCELLED);
    if (!report("starting", 0)) return failed(ERROR_WRITE_FAULT);
    OutputDebugStringA("[steam-bootstrap] starting Steam through prepared desktop/services route");
    error = start_desktop(client_command, &process);
    if (error) return failed(error);
    CloseHandle(process.hThread);
    if (!report("waiting", 0)) {
        TerminateProcess(process.hProcess, ERROR_WRITE_FAULT); CloseHandle(process.hProcess);
        return failed(ERROR_WRITE_FAULT);
    }
    error = wait_program(process.hProcess, &code);
    CloseHandle(process.hProcess);
    /* Wine's existing child wait retains updater-created Steam successors. */
    return error || code ? failed(error ? error : code) : ERROR_SUCCESS;
}

#ifndef MADEIRA_BOOTSTRAP_HOST_TEST
void __cdecl mainCRTStartup(void) { ExitProcess(bootstrap_run()); }
#endif
