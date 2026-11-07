#!/usr/bin/env python3
"""Prepare the native iOS window implementation without editing the Wine pin."""
from pathlib import Path
import sys

ORIGINAL = '''    if ((win = get_user_handle_ptr( hwnd, NTUSER_OBJ_WINDOW )) == WND_OTHER_PROCESS)
    {
        if (is_desktop_window( hwnd )) win = WND_DESKTOP;
    }
'''
REPLACEMENT = '''    win = get_user_handle_ptr( hwnd, NTUSER_OBJ_WINDOW );
    /* iOS creates and detaches the desktop on behalf of the first process.
     * Its server handle may still name that process although there is no
     * client_objects entry. Treat the known desktop/message root as the
     * traversal sentinel even then; otherwise GA_ROOT fails at the desktop
     * and process_mouse_message discards a child button's press. Both NULL
     * and WND_OTHER_PROCESS arrive here with user_lock already released. */
    if ((!win || win == WND_OTHER_PROCESS) && is_desktop_window( hwnd ))
        win = WND_DESKTOP;
'''


def prepare(source):
    if source.count(ORIGINAL) != 1:
        raise ValueError('Wine get_win_ptr changed; review the iOS desktop lookup adaptation')
    return source.replace(ORIGINAL, REPLACEMENT, 1)


if __name__ == '__main__':
    Path(sys.argv[2]).write_text(prepare(Path(sys.argv[1]).read_text()))
