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

    LONG private_count = state->initial_worker;
    if (private_count != InterlockedCompareExchange(&state->completed, 0, 0) ||
        !PostMessageW(state->window, WORKER_READY, (WPARAM)private_count, 0)) return 4;
    for (;;) {
        DWORD wake = WaitForMultipleObjects(ARRAYSIZE(waits), waits, FALSE, INFINITE);
        if (wake == WAIT_OBJECT_0) return 0;
        if (wake != WAIT_OBJECT_0 + 1) return 4;
        LONG operation = InterlockedExchange(&state->operation, IDLE);
        if (operation == INCREMENT) {
            if (private_count == LONG_MAX) return 5;
            LONG count = InterlockedIncrement(&state->completed);
            if (count != ++private_count) return 5;
        } else if (operation != CAPTURE) {
            return 5;
        }
        if (!PostMessageW(state->window, WORKER_REPLY, (WPARAM)private_count, operation)) return 6;
    }
}
