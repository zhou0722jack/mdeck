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

static DWORD bootstrap_run(void) {
    PROCESS_INFORMATION process;
    DWORD error, code = 0, attributes;
    WCHAR setup_command[] = L"\"C:\\Madeira\\Installers\\SteamSetup.exe\" /D=C:\\Program Files\\Steam Client";
    /* The native steam.exe child rule appends SteamClient.clientArguments,
     * including sandbox/GPU compatibility, also on updater restarts. */
    WCHAR client_command[1024];
    if (cancelled()) return failed(ERROR_CANCELLED);
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
    error = register_libraries();
    if (error) return failed(error);
    error = read_desktop_command(client_command, sizeof(client_command) / sizeof(*client_command));
    if (error) return failed(error);
    if (cancelled()) return failed(ERROR_CANCELLED);
    if (!report("starting", 0)) return failed(ERROR_WRITE_FAULT);
    OutputDebugStringA("[steam-bootstrap] starting Steam through prepared desktop/services route");
    if (!start_program(desktop_path, client_command, client_dir, &process)) return failed(GetLastError());
    CloseHandle(process.hThread);
    if (!report("waiting", 0)) {
        TerminateProcess(process.hProcess, ERROR_WRITE_FAULT); CloseHandle(process.hProcess);
        return failed(ERROR_WRITE_FAULT);
    }
    error = wait_program(process.hProcess, &code);
    CloseHandle(process.hProcess);
    /* Wine's existing child wait retains updater-created Steam successors. */
    return error ? failed(error) : code;
}

#ifndef MADEIRA_BOOTSTRAP_HOST_TEST
void __cdecl mainCRTStartup(void) { ExitProcess(bootstrap_run()); }
#endif
