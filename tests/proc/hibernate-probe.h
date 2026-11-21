#ifndef MDECK_HIBERNATE_PROBE_H
#define MDECK_HIBERNATE_PROBE_H

#include <stdint.h>
#include <windows.h>

enum { WORKER_REPLY = WM_APP + 1, WORKER_READY };
enum work_kind { IDLE, INCREMENT, CAPTURE };

/* Fixed little-endian records exchanged with Madeira. Win32 objects and
 * pointers are rebuilt on the next launch and are absent from these records. */
enum { CHECKPOINT_VERSION = 1, CHECKPOINT_TOKEN_SIZE = 16 };
#define CHECKPOINT_REQUEST L"snapshot-request.bin"
#define CHECKPOINT_REPLY L"snapshot-reply.bin"
#define CHECKPOINT_REPLY_TEMP L"snapshot-reply.tmp"
#define CHECKPOINT_RESTORE L"snapshot-restore.bin"

struct checkpoint_state {
    uint64_t session;
    int32_t displayed, completed, worker;
    uint32_t version;
};

struct checkpoint_reply {
    unsigned char token[CHECKPOINT_TOKEN_SIZE];
    struct checkpoint_state state;
};

_Static_assert(sizeof(struct checkpoint_state) == 24, "checkpoint state size");
_Static_assert(sizeof(struct checkpoint_reply) == 40, "checkpoint reply size");

struct shared_state {
    HWND window;
    volatile LONG completed;
    ULONGLONG session;
    volatile LONG operation;
    LONG initial_worker;
};

#endif
