/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Runs only on the pinned SteamSetup.exe's own Wine GUI thread. */
#include "steam_installer_policy.h"

static int steam_setup_ascii_equal( const WCHAR *text, unsigned count, const char *expected )
{
    unsigned i = 0, start = 0, length = strlen( expected );
    if (count >= 4 && text[0] == '\\' && text[1] == '?' && text[2] == '?' && text[3] == '\\') start = 4;
    if (count - start && (text[count - 1] == '\\' || text[count - 1] == '/')) count--;
    if (count - start != length) return 0;
    for (; i < length; i++) {
        WCHAR c = text[start + i];
        char e = expected[i];
        if (c >= 'A' && c <= 'Z') c += 32;
        if (e >= 'A' && e <= 'Z') e += 32;
        if (c == '/') c = '\\';
        if (c != (unsigned char)e) return 0;
    }
    return 1;
}

static int steam_setup_class( HWND hwnd, const char *name )
{
    WCHAR text[32];
    UNICODE_STRING value = { .Buffer = text, .MaximumLength = sizeof(text) };
    return NtUserGetClassName( hwnd, FALSE, &value ) > 0 &&
        steam_setup_ascii_equal( text, value.Length / sizeof(WCHAR), name );
}

static void ios_steam_installer_poll(void)
{
    static __thread struct steam_setup_state state;
    static __thread unsigned calls, failures, manual_note;
    static __thread uint64_t next_poll;
    HWND windows[32], children[128];
    ULONG count, i;
    uint64_t now;
    const RTL_USER_PROCESS_PARAMETERS *params;
    const char *enabled = getenv( "MADEIRA_STEAM_AUTOINSTALL" );

    if (!enabled || enabled[0] != '1' || enabled[1] || state.finished || ((++calls & 31) != 0)) return;
    now = ios_tiny_now_ns() / 1000000;
    if (now < next_poll) return;
    next_poll = now + 150;
    params = NtCurrentTeb()->Peb->ProcessParameters;
    if (!params || !params->ImagePathName.Buffer ||
        !steam_setup_ascii_equal( params->ImagePathName.Buffer, params->ImagePathName.Length / sizeof(WCHAR),
                                 "c:\\madeira\\installers\\steamsetup.exe" )) return;
    count = ARRAY_SIZE(windows);
    if (NtUserBuildHwndList( 0, 0, FALSE, TRUE, GetCurrentThreadId(), count, windows, &count )) return;
    for (i = 0; i + 1 < count && i < ARRAY_SIZE(windows); i++) {
        HWND dialog = windows[i], button = 0, page = 0;
        ULONG total = ARRAY_SIZE(children), j;
        unsigned pages = 0;
        int directory_ok = 0, ready;
        WCHAR label[64];
        int label_length;
        enum steam_setup_action role, action;
        if (get_window_thread( dialog, NULL ) != GetCurrentThreadId() ||
            !is_window_visible( dialog ) || !NtUserIsWindowEnabled( dialog ) || !steam_setup_class( dialog, "#32770" )) continue;
        if (NtUserBuildHwndList( 0, dialog, TRUE, TRUE, 0, total, children, &total )) continue;
        for (j = 0; j + 1 < total && j < ARRAY_SIZE(children); j++) {
            HWND child = children[j];
            if (!is_window_visible( child ) || get_window_thread( child, NULL ) != GetCurrentThreadId()) continue;
            if (NtUserGetAncestor( child, GA_PARENT ) == dialog) {
                if (get_window_long( child, GWLP_ID ) == IDOK && steam_setup_class( child, "Button" )) button = child;
                if (steam_setup_class( child, "#32770" )) { page = child; pages++; }
            }
            if (steam_setup_class( child, "Edit" )) {
                WCHAR folder[260];
                int length = NtUserInternalGetWindowText( child, folder, ARRAY_SIZE(folder) );
                if (length > 0 && steam_setup_ascii_equal( folder, length, "c:\\program files\\steam client" )) directory_ok = 1;
            }
        }
        ready = button && page && pages == 1 && NtUserIsWindowEnabled( button );
        label_length = button ? NtUserInternalGetWindowText( button, label, ARRAY_SIZE(label) ) : 0;
        role = steam_setup_role( (const uint16_t *)label, label_length > 0 ? (size_t)label_length : 0 );
        action = steam_setup_observe( &state, (uintptr_t)page, role, ready, directory_ok, now );
        if (!action) {
            if (ready && !manual_note && (role == STEAM_SETUP_NONE || (role == STEAM_SETUP_INSTALL && !directory_ok))) {
                manual_note = 1;
                dprintf(2, "[steam-autoinstall] unknown page or changed directory; leaving controls available for manual input\n");
            }
            continue;
        }
        /* Equivalent to activating this particular button, without focus,
         * keyboard shortcuts, pixel coordinates or cross-thread SendMessage. */
        if (NtUserPostMessage( dialog, WM_COMMAND, MAKEWPARAM(IDOK, BN_CLICKED), (LPARAM)button )) {
            steam_setup_posted( &state, action );
            dprintf(2, "[steam-autoinstall] %s posted; next=%u page=%p button=%p\n",
                    action == STEAM_SETUP_NEXT ? "Next" : action == STEAM_SETUP_INSTALL ? "Install" : "Finish",
                    state.next_count, (void *)page, (void *)button );
        } else if (++failures >= 3) {
            state.finished = 1;
            dprintf(2, "[steam-autoinstall] button post failed three times; stopped for manual input\n");
        }
        return;
    }
}
