/* Synthetic inputs only. Production PE/native code is inserted by the checker. */
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <wchar.h>
#include <wctype.h>

typedef int BOOL, NTSTATUS;
typedef unsigned int DWORD, PTR32;
typedef int32_t LONG;
typedef unsigned char BYTE;
typedef wchar_t WCHAR;
typedef struct { DWORD cbData; BYTE *pbData; } DATA_BLOB;

// PRODUCTION_DEFINITIONS

#define MAX_PATH 260
#define STATUS_SUCCESS 0
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
static const WCHAR *image = L"C:\\Program Files\\Steam Client\\Steam.exe";
static DWORD last_error = 7;
static DWORD GetLastError(void) { return last_error; }
static void SetLastError(DWORD error) { last_error = error; }
static DWORD GetModuleFileNameW(void *module, WCHAR *path, DWORD size)
{
    size_t len;
    assert(!module);
    last_error = 123;
    if (!image) return 0;
    len = wcslen(image);
    if (len >= size) return size;
    wcscpy(path, image);
    return len;
}
static int lstrcmpiW(const WCHAR *a, const WCHAR *b)
{
    while (*a && towlower(*a) == towlower(*b)) { a++; b++; }
    return towlower(*a) - towlower(*b);
}
static LONG InterlockedOr(LONG *target, LONG bit)
{
    return __atomic_fetch_or(target, bit, __ATOMIC_RELAXED);
}

static unsigned calls, events[MDECK_STEAM_EVENT_LAST + 1];
static struct { unsigned size; BYTE bytes[16386]; } samples[16];
extern void madeira_steam_token_received(const void *, unsigned int) __attribute__((weak));
void madeira_steam_token_received(const void *bytes, unsigned int size)
{
    if (!bytes)
    {
        assert(size >= MDECK_STEAM_MONITOR_ATTACHED && size <= MDECK_STEAM_EVENT_LAST);
        events[size]++;
    }
    else
    {
        assert(size >= 128 && size <= 16386 && calls < ARRAY_SIZE(samples));
        samples[calls].size = size;
        memcpy(samples[calls++].bytes, bytes, size);
    }
    /* A callback must not leak its thread's LastError change into DPAPI. */
    last_error = 999;
}

// PRODUCTION_NATIVE

#define CRYPT32_CALL(name, args) mdeck_steam_token(args)

// PRODUCTION_HANDLERS

static BYTE region[20000];
static void *ios_wow_host_ptr(PTR32 address)
{
    assert(address < sizeof(region));
    return address ? region + address : NULL;
}

// PRODUCTION_WOW64

// SYNTHETIC_TOKEN

static void publish(BYTE *data, unsigned size)
{
    DATA_BLOB blob = { size, data };
    last_error = 7;
    mdeck_publish_token(&blob);
    assert(last_error == 7);
}
static void expect_ascii(unsigned index)
{
    assert(samples[index].size == strlen(jwt));
    assert(!memcmp(samples[index].bytes, jwt, strlen(jwt)));
}
static void expect_utf16(unsigned index)
{
    unsigned i;
    assert(samples[index].size == 2 * strlen(jwt));
    for (i = 0; i < strlen(jwt); i++)
        assert(samples[index].bytes[2 * i] == (BYTE)jwt[i] && !samples[index].bytes[2 * i + 1]);
}

int main(void)
{
    BYTE data[65537], wide[16386];
    char maximal[8194];
    WCHAR long_path[MAX_PATH + 1];
    const unsigned n = strlen(jwt);
    unsigned i, before;

    /* Attach/identity metadata works even when Steam never calls DPAPI. */
    mdeck_steam_auth_probe();
    assert(last_error == 7 && !calls);
    assert(events[MDECK_STEAM_MONITOR_ATTACHED] == 1 && events[MDECK_STEAM_SCOPE_INTERACTIVE] == 1);
    mdeck_steam_auth_probe();
    assert(events[MDECK_STEAM_MONITOR_ATTACHED] == 1);
    assert(mdeck_steam_process() && last_error == 7);
    image = L"c:\\program files\\steam client\\STEAM.EXE";
    assert(mdeck_steam_process());
    publish((BYTE *)jwt, n); assert(calls == 1); expect_ascii(0);
    publish((BYTE *)jwt, n + 1); assert(calls == 2); expect_ascii(1);

    memset(data, 0, sizeof(data));
    memcpy(data, "wrapper=\"", 9); memcpy(data + 9, jwt, n); memcpy(data + 9 + n, "\";password=fixture", 19);
    publish(data, n + 28); assert(calls == 3); expect_ascii(2);
    memset(data, 0, sizeof(data)); memcpy(data + 15, jwt, n);
    publish(data, sizeof(data) - 1); assert(calls == 4); expect_ascii(3);

    memset(wide, 0, sizeof(wide));
    for (i = 0; i < n; i++) wide[2 * i] = jwt[i];
    publish(wide, 2 * n); assert(calls == 5); expect_utf16(4);
    publish(wide, 2 * n + 2); assert(calls == 6); expect_utf16(5);
    memset(data, 0, sizeof(data)); data[0] = 0xff; data[2] = 0xfe;
    memcpy(data + 3, wide, 2 * n);
    publish(data, 2 * n + 7); assert(calls == 7); expect_utf16(6);
    publish(wide, 2 * n - 1); assert(calls == 7); /* Incomplete UTF-16 character. */

    image = L"C:\\Program Files (x86)\\Steam\\steam.exe";
    assert(!mdeck_steam_process()); mdeck_steam_auth_probe(); publish((BYTE *)jwt, n);
    image = L"C:\\Other\\Steam.exe";
    assert(!mdeck_steam_process()); publish((BYTE *)jwt, n);
    image = L"C:\\Program Files\\Steam Client\\steamwebhelper.exe";
    assert(!mdeck_steam_process()); mdeck_steam_auth_probe(); publish((BYTE *)jwt, n);
    image = L"C:\\windows\\system32\\explorer.exe";
    mdeck_steam_auth_probe(); publish((BYTE *)jwt, n);
    image = NULL; mdeck_steam_auth_probe(); publish((BYTE *)jwt, n);
    for (i = 0; i < MAX_PATH; i++) long_path[i] = 'a';
    long_path[MAX_PATH] = 0; image = long_path;
    assert(!mdeck_steam_process()); publish((BYTE *)jwt, n);
    assert(calls == 7 && events[MDECK_STEAM_SCOPE_OTHER_STEAM] == 1);
    assert(events[MDECK_STEAM_SCOPE_WEBHELPER] == 1 && events[MDECK_STEAM_SCOPE_OTHER] == 1);
    assert(events[MDECK_STEAM_SCOPE_UNKNOWN] == 1 && last_error == 7);
    image = L"C:\\Program Files\\Steam Client\\Steam.exe";

    /* These must not export a partial, embedded or malformed JWT. */
    memcpy(data, jwt, n); memcpy(data + n, ".fourth", 8); publish(data, n + 7);
    memcpy(data + 1, jwt, n); data[0] = 'A'; publish(data, n + 1);
    memcpy(data, jwt, n + 1); *strrchr((char *)data, '.') = 0; publish(data, n);
    memset(data, 'A', 400); memcpy(data, "eyJ..", 5); publish(data, 400);
    memset(data, 'A', 400); memcpy(data, "eyJ", 3); publish(data, 400);
    memset(data, 0, 400); memcpy(data, "eyJab.cd.ef", 11); publish(data, 400);
    memset(data, 'x', 400); memcpy(data, "password fixture", 16); publish(data, 400);
    assert(calls == 7 && events[MDECK_STEAM_NO_JWT] == 1);
    publish(NULL, n); publish(data, 127); publish(data, sizeof(data)); mdeck_publish_token(NULL);
    assert(calls == 7 && events[MDECK_STEAM_BLOB_SKIPPED] == 1 && last_error == 7);

    /* Exactly 8192 characters are allowed; 8193 are never truncated/exported. */
    calls = 0;
    memset(maximal, 'A', sizeof(maximal)); memcpy(maximal, "eyJ", 3);
    maximal[10] = maximal[40] = '.'; maximal[8192] = 0;
    publish((BYTE *)maximal, 8192); assert(calls == 1 && samples[0].size == 8192);
    for (i = 0; i < 8192; i++) { wide[2 * i] = maximal[i]; wide[2 * i + 1] = 0; }
    publish(wide, 16384); assert(calls == 2 && samples[1].size == 16384);
    maximal[8192] = 'A'; maximal[8193] = 0;
    publish((BYTE *)maximal, 8193); assert(calls == 2);
    wide[16384] = 'A'; wide[16385] = 0;
    publish(wide, 16386); assert(calls == 2);

    /* Multiple candidates preserve slices and stop after four. */
    calls = 0;
    for (i = 0; i < 6; i++) { memcpy(data + i * (n + 1), jwt, n); data[i * (n + 1) + n] = '\n'; }
    publish(data, 6 * (n + 1)); assert(calls == 4);
    for (i = 0; i < 4; i++) expect_ascii(i);

    /* Native and WoW64 reject unknown metadata and bad sizes. */
    calls = 0;
    memcpy(region + 128, jwt, n);
    struct { PTR32 data; unsigned int size; } p = { 128, n };
    wow64_mdeck_steam_token(&p); assert(calls == 1); expect_ascii(0);
    before = events[MDECK_STEAM_MONITOR_ATTACHED];
    p.data = 0; p.size = MDECK_STEAM_MONITOR_ATTACHED;
    wow64_mdeck_steam_token(&p); assert(events[MDECK_STEAM_MONITOR_ATTACHED] == before + 1);
    p.size = 0; wow64_mdeck_steam_token(&p);
    p.size = MDECK_STEAM_EVENT_LAST + 1; wow64_mdeck_steam_token(&p);
    p.data = 128; p.size = 127; wow64_mdeck_steam_token(&p);
    p.size = 20000; wow64_mdeck_steam_token(&p);
    wow64_mdeck_steam_token(NULL); mdeck_steam_token(NULL);
    assert(calls == 1 && events[MDECK_STEAM_MONITOR_ATTACHED] == before + 1);
    return 0;
}
