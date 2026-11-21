#ifndef MDECK_HIBERNATE_PROBE_H
#define MDECK_HIBERNATE_PROBE_H

#include <windows.h>

enum { WORKER_REPLY = WM_APP + 1 };

struct shared_state {
    HWND window;
    volatile LONG completed;
    ULONGLONG session;
};

#endif
