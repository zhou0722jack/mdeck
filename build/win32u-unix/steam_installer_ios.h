/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Runs only on the pinned SteamSetup.exe's own Wine GUI thread. */
#include "steam_installer_policy.h"
extern void winios_steam_setup_note(int step, int percent, int blocked) __attribute__((weak));

static void steam_setup_progress(int step, int percent, int blocked) {
    if (winios_steam_setup_note) winios_steam_setup_note(step, percent, blocked);
}

static int steam_setup_run_checkbox(const WCHAR *text, int length) {
    int steam = 0, run = 0, i;
    for (i = 0; i < length; i++) {
        if (i + 5 <= length && (text[i] == 'S' || text[i] == 's') && text[i+1] == 't' && text[i+2] == 'e' && text[i+3] == 'a' && text[i+4] == 'm') steam = 1;
        if (i + 3 <= length && (text[i] == 'R' || text[i] == 'r') && (text[i+1] == 'u' || text[i+1] == 'U') && (text[i+2] == 'n' || text[i+2] == 'N')) run = 1;
        if (i + 2 <= length && ((text[i] == 0x8fd0 && text[i+1] == 0x884c) || (text[i] == 0x542f && text[i+1] == 0x52a8))) run = 1;
    }
    return steam && run;
}

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
    /* NtUserGetClassName returns a WCHAR count; it does not set Length. */
    int length = NtUserGetClassName( hwnd, FALSE, &value );
    return length > 0 && steam_setup_ascii_equal( text, length, name );
}

static void ios_steam_installer_poll(void)
{
    static __thread struct steam_setup_state state;
    static __thread unsigned calls, failures, manual_note, announced, reading_directory;
    static __thread uint64_t next_poll;
    static __thread HWND noted_dialog, noted_page, noted_button;
    static __thread int noted_role = -1, noted_ready = -1, noted_directory = -1;
    static __thread WCHAR noted_folder[260];
    static __thread unsigned noted_folder_length, folder_announced;
    static __thread HWND blocked_page;
    static __thread int blocked_kind;
    static __thread uint64_t blocked_since;
    HWND windows[32], children[128];
    ULONG count, i;
    uint64_t now;
    const RTL_USER_PROCESS_PARAMETERS *params;
    const char *enabled = getenv( "MADEIRA_STEAM_AUTOINSTALL" );

    if (!enabled || enabled[0] != '1' || enabled[1] || state.finished || reading_directory || ((++calls & 31) != 0)) return;
    now = ios_tiny_now_ns() / 1000000;
    if (now < next_poll) return;
    next_poll = now + 150;
    params = NtCurrentTeb()->Peb->ProcessParameters;
    if (!params || !params->ImagePathName.Buffer ||
        !steam_setup_ascii_equal( params->ImagePathName.Buffer, params->ImagePathName.Length / sizeof(WCHAR),
                                 "c:\\madeira\\installers\\steamsetup.exe" )) return;
    if (!announced) {
        announced = 1;
        dprintf(2, "[steam-autoinstall] enabled on installer GUI thread %04x\n", (unsigned)GetCurrentThreadId());
    }
    count = ARRAY_SIZE(windows);
    if (NtUserBuildHwndList( 0, 0, FALSE, TRUE, GetCurrentThreadId(), count, windows, &count )) return;
    for (i = 0; i + 1 < count && i < ARRAY_SIZE(windows); i++) {
        HWND dialog = windows[i], button = 0, page = 0;
        ULONG total = ARRAY_SIZE(children), j;
        unsigned pages = 0;
        int directory_ok = 0, ready, percent = -1;
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
                WCHAR folder[260] = {0};
                LRESULT length;
                /* Edit owns its text in EDITSTATE, not WND.text. Read it via
                 * the normal Unicode message on its own GUI thread. The
                 * message path marshals the buffer for the 32-bit control.
                 * A nested driver poll during its callback must not re-enter. */
                reading_directory = 1;
                length = send_message_timeout( child, WM_GETTEXT, ARRAY_SIZE(folder), (LPARAM)folder,
                                               SMTO_ABORTIFHUNG, 250, FALSE );
                reading_directory = 0;
                if (length < 0 || (size_t)length >= ARRAY_SIZE(folder)) length = 0;
                folder[length] = 0;
                if (!folder_announced || (unsigned)length != noted_folder_length || memcmp(noted_folder, folder, length * sizeof(WCHAR))) {
                    char shown[260];
                    unsigned k;
                    for (k = 0; k < (unsigned)length; k++) shown[k] = folder[k] >= 32 && folder[k] < 127 ? (char)folder[k] : '?';
                    shown[k] = 0;
                    dprintf(2, "[steam-autoinstall] directory read via WM_GETTEXT: chars=%u value=\"%s\"\n", (unsigned)length, shown);
                    memcpy(noted_folder, folder, (length + 1) * sizeof(WCHAR)); noted_folder_length = length; folder_announced = 1;
                }
                if (length > 0 && steam_setup_ascii_equal( folder, length, "c:\\program files\\steam client" )) directory_ok = 1;
            }
            if (steam_setup_class(child, "msctls_progress32")) {
                LRESULT low, high, position;
                reading_directory = 1;
                low = send_message_timeout(child, WM_USER + 7, TRUE, 0, SMTO_ABORTIFHUNG, 250, FALSE);
                high = send_message_timeout(child, WM_USER + 7, FALSE, 0, SMTO_ABORTIFHUNG, 250, FALSE);
                position = send_message_timeout(child, WM_USER + 8, 0, 0, SMTO_ABORTIFHUNG, 250, FALSE);
                reading_directory = 0;
                if (high > low && position >= low && position <= high) percent = (int)((position - low) * 100 / (high - low));
            }
        }
        ready = button && page && pages == 1 && NtUserIsWindowEnabled( button );
        label_length = button ? NtUserInternalGetWindowText( button, label, ARRAY_SIZE(label) ) : 0;
        role = steam_setup_role( (const uint16_t *)label, label_length > 0 ? (size_t)label_length : 0 );
        steam_setup_progress(state.installing ? (role == STEAM_SETUP_FINISH ? 5 : 4) : (int)state.next_count + 1, percent, 0);
        if (noted_dialog != dialog || noted_page != page || noted_button != button || noted_role != (int)role ||
            noted_ready != ready || noted_directory != directory_ok) {
            dprintf(2, "[steam-autoinstall] observed dialog=%p page=%p pages=%u button=%p role=%d ready=%d directory=%d\n",
                    (void *)dialog, (void *)page, pages, (void *)button, (int)role, ready, directory_ok);
            noted_dialog = dialog; noted_page = page; noted_button = button; noted_role = role;
            noted_ready = ready; noted_directory = directory_ok;
        }
        action = steam_setup_observe( &state, (uintptr_t)page, role, ready, directory_ok, now );
        if (!action) {
            if (ready && !manual_note && (role == STEAM_SETUP_NONE || (role == STEAM_SETUP_INSTALL && !directory_ok))) {
                manual_note = 1;
                dprintf(2, "[steam-autoinstall] unknown page or changed directory; leaving controls available for manual input\n");
            }
            int reason = ready && role == STEAM_SETUP_NONE ? 1 : ready && role == STEAM_SETUP_INSTALL && !directory_ok ? 2 : 0;
            if (!reason) { blocked_page = 0; blocked_kind = 0; }
            else if (blocked_page != page || blocked_kind != reason) {
                blocked_page = page; blocked_kind = reason; blocked_since = now;
            } else if (now >= blocked_since && now - blocked_since >= 3000) {
                steam_setup_progress((int)state.next_count + 1, percent, reason);
            }
            continue;
        }
        const char *controlled = getenv("MADEIRA_STEAM_CONTROLLED_SETUP");
        if (action == STEAM_SETUP_FINISH && controlled && controlled[0] == '1' && !controlled[1]) {
            /* The session controller, not the wizard's checkbox, owns launch.
             * Clear only the recognized Run Steam checkbox and verify it. */
            for (j = 0; j + 1 < total && j < ARRAY_SIZE(children); j++) {
                HWND child = children[j];
                WCHAR text[96];
                int length;
                DWORD type;
                if (!is_window_visible(child) || get_window_thread(child, NULL) != GetCurrentThreadId() || !steam_setup_class(child, "Button")) continue;
                type = get_window_long(child, GWL_STYLE) & BS_TYPEMASK;
                if (type != BS_CHECKBOX && type != BS_AUTOCHECKBOX) continue;
                length = NtUserInternalGetWindowText(child, text, ARRAY_SIZE(text));
                if (!steam_setup_run_checkbox(text, length)) continue;
                reading_directory = 1;
                send_message_timeout(child, BM_SETCHECK, BST_UNCHECKED, 0, SMTO_ABORTIFHUNG, 250, FALSE);
                LRESULT checked = send_message_timeout(child, BM_GETCHECK, 0, 0, SMTO_ABORTIFHUNG, 250, FALSE);
                reading_directory = 0;
                if (checked != BST_UNCHECKED) { steam_setup_progress(5, -1, 3); return; }
                dprintf(2, "[steam-autoinstall] Run Steam unchecked; controller launches after installer exit\n");
            }
        }
        /* Equivalent to activating this particular button, without focus,
         * keyboard shortcuts, pixel coordinates or cross-thread SendMessage. */
        if (NtUserPostMessage( dialog, WM_COMMAND, MAKEWPARAM(IDOK, BN_CLICKED), (LPARAM)button )) {
            steam_setup_posted( &state, action );
            steam_setup_progress(action == STEAM_SETUP_NEXT ? (int)state.next_count + 1 : action == STEAM_SETUP_INSTALL ? 4 : 5, -1, 0);
            dprintf(2, "[steam-autoinstall] %s posted; next=%u page=%p button=%p\n",
                    action == STEAM_SETUP_NEXT ? "Next" : action == STEAM_SETUP_INSTALL ? "Install" : "Finish",
                    state.next_count, (void *)page, (void *)button );
        } else if (++failures >= 3) {
            state.finished = 1;
            steam_setup_progress((int)state.next_count + 1, -1, 3);
            dprintf(2, "[steam-autoinstall] button post failed three times; stopped for manual input\n");
        }
        return;
    }
}
