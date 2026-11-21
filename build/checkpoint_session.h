#ifndef MADEIRA_CHECKPOINT_SESSION_H
#define MADEIRA_CHECKPOINT_SESSION_H

#include "win32u-unix/checkpoint_message.h"
#include "wineserver/checkpoint_server.h"

/* The visitor borrows both arrays on the Wine server thread while every
 * listed client is parked before its lower wait. A session containing any
 * thread that does not reach this boundary returns without a visit. The
 * visitor consumes data synchronously and must not enter Wine or wait on a
 * client. Drivers and the emulator supply their own state separately. */
typedef unsigned int (*ios_checkpoint_session_visitor)(const struct ios_checkpoint_roster *,
    const struct ios_checkpoint_message_wait *, void *);
unsigned int ios_checkpoint_visit_message_session(uint32_t timeout_ms,
    ios_checkpoint_session_visitor visit, void *context);
#endif
