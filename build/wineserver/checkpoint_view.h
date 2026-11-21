#ifndef MADEIRA_CHECKPOINT_SERVER_VIEW_H
#define MADEIRA_CHECKPOINT_SERVER_VIEW_H

#include "../checkpoint_view.h"

struct fd;
struct object;
struct process;
/* The session interns each borrowed Wine fd once, including fds held only
 * by views after the last section handle was closed. */
typedef unsigned int (*ios_checkpoint_backing_id)(void *, struct fd *, int unix_fd,
                                                 uint64_t bytes, uint64_t *id);
typedef unsigned int (*ios_checkpoint_emit_view)(void *, const struct ios_checkpoint_view *);

unsigned int ios_checkpoint_section_backing(struct object *, ios_checkpoint_backing_id, void *, uint64_t *);
unsigned int ios_checkpoint_capture_section_views(struct process *, ios_checkpoint_backing_id,
                                                  ios_checkpoint_emit_view, void *);

#endif
