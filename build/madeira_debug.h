/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef MADEIRA_DEBUG_H
#define MADEIRA_DEBUG_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "madeira_cfg.h"

extern int madeira_get_diag_enabled(void);

/* Wine caches channel options on their first use, before the guest's env loop. */
static inline void madeira_configure_wine_debug(void)
{
    char configured[4096], verbose_config[64], selected[8192];
    const char *verbose = getenv("MADEIRA_DEBUG_VERBOSE");
    const char *channels;
    const char *source;
    int extended = madeira_get_diag_enabled();

    if (madeira_cfg_get("env.WINEDEBUG", configured, sizeof(configured)))
    {
        channels = configured;
        source = "config";
    }
    else
    {
        if (madeira_cfg_get("env.MADEIRA_DEBUG_VERBOSE", verbose_config, sizeof(verbose_config)))
            verbose = verbose_config;
        if (verbose && *verbose && *verbose != '0')
        {
            channels = "err+all,fixme+all,warn+module,warn+file,trace+process,trace+module,trace+loaddll,trace+loadorder,trace+win,trace+user32,trace+syscall,trace+file";
            source = "verbose";
        }
        else
        {
            channels = "err+all,err-virtual,fixme-d3dcompiler";
            source = "default";
        }
    }
    if (extended)
    {
        snprintf(selected, sizeof(selected), "%s,trace+msvcrt,trace+nls", channels);
        channels = selected;
    }
    setenv("WINEDEBUG", channels, 1);
    if (extended) fprintf(stderr, "[wine-debug] source=%s channels=%s\n", source, channels);
}

#endif
