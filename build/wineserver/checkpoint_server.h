#ifndef MADEIRA_CHECKPOINT_SERVER_H
#define MADEIRA_CHECKPOINT_SERVER_H

#include <stddef.h>
#include <stdint.h>

struct ios_checkpoint_client
{
    uint32_t pid, tid;
};

/* A roster belongs to exactly one running Wine server. A new thread, an
 * exit or a new server requires starting the capture again. */
struct ios_checkpoint_roster
{
    uint64_t session;
    size_t count;
    struct ios_checkpoint_client *clients;
};

unsigned int ios_checkpoint_get_roster(struct ios_checkpoint_roster *, uint32_t timeout_ms);
/* Called by the coordinator after the listed clients have entered their
 * individual safe points. The callback runs on the server thread, between
 * requests, while timers and direct requests cannot change the Wine graph.
 * It must not wait for a Wine client or issue a Wine server request. */
unsigned int ios_checkpoint_visit_parked(const struct ios_checkpoint_roster *,
                                         uint32_t timeout_ms, unsigned int (*visit)(void *), void *);
#endif
