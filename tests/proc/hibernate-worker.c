#include "hibernate-probe.h"
#include <limits.h>
#include <wchar.h>

int wmain(int argc, wchar_t **argv)
{
    if (argc != 4) return 1;
    DWORD parent_pid = wcstoul(argv[1], NULL, 10);
    HANDLE mapping = OpenFileMappingW(FILE_MAP_ALL_ACCESS, FALSE, argv[2]);
    HANDLE waits[] = { OpenProcess(SYNCHRONIZE, FALSE, parent_pid),
                       OpenEventW(SYNCHRONIZE, FALSE, argv[3]) };
    if (!mapping || !waits[0] || !waits[1]) return 2;
    struct shared_state *state = MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(*state));
    if (!state) return 3;

    LONG private_count = 0;
    for (;;) {
        DWORD wake = WaitForMultipleObjects(ARRAYSIZE(waits), waits, FALSE, INFINITE);
        if (wake == WAIT_OBJECT_0) return 0;
        if (wake != WAIT_OBJECT_0 + 1 || private_count == LONG_MAX) return 4;
        LONG count = InterlockedIncrement(&state->completed);
        if (count != ++private_count) return 5;
        if (!PostMessageW(state->window, WORKER_REPLY, (WPARAM)count, 0)) return 6;
    }
}
