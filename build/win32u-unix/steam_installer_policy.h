/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Official NSIS Steam wizard policy. No timers that blindly emit keystrokes. */
#ifndef MADEIRA_STEAM_INSTALLER_POLICY_H
#define MADEIRA_STEAM_INSTALLER_POLICY_H
#include <stdint.h>
#include <stddef.h>

enum steam_setup_action { STEAM_SETUP_NONE, STEAM_SETUP_NEXT, STEAM_SETUP_INSTALL, STEAM_SETUP_FINISH };
struct steam_setup_state {
    uintptr_t page, last_page;
    unsigned next_count;
    enum steam_setup_action role, last_role;
    uint64_t since_ms;
    int installing, finished;
};

/* Matches the pinned installer's English and Simplified Chinese labels.
 * The adapter also requires IDOK on a Button, on SteamSetup's own dialog. */
static enum steam_setup_action steam_setup_role( const uint16_t *text, size_t length )
{
    uint16_t plain[48];
    size_t count = 0, i;
    static const char * const english[] = { "", "next", "install", "finish" };
    if (!text) return STEAM_SETUP_NONE;
    for (i = 0; i < length && count < 48; i++) {
        uint16_t c = text[i];
        if (!c) break;
        if (c == '&' || c == ' ' || c == '\t' || c == '(' || c == ')' || c == '>' || c == '<') continue;
        plain[count++] = c >= 'A' && c <= 'Z' ? c + 32 : c;
    }
    for (i = 1; i <= 3; i++) {
        size_t k;
        for (k = 0; english[i][k] && k < count && plain[k] == (unsigned char)english[i][k]; k++);
        if (!english[i][k] && (count == k || (count == k + 1 && plain[k] == (i == 1 ? 'n' : i == 2 ? 'i' : 'f'))))
            return (enum steam_setup_action)i;
    }
    if (count >= 3 && plain[0] == 0x4e0b && plain[1] == 0x4e00 && plain[2] == 0x6b65 &&
        (count == 3 || (count == 4 && plain[3] == 'n'))) return STEAM_SETUP_NEXT;
    if (count >= 2 && plain[0] == 0x5b89 && plain[1] == 0x88c5 &&
        (count == 2 || (count == 3 && plain[2] == 'i'))) return STEAM_SETUP_INSTALL;
    if (count >= 2 && plain[0] == 0x5b8c && plain[1] == 0x6210 &&
        (count == 2 || (count == 3 && plain[2] == 'f'))) return STEAM_SETUP_FINISH;
    return STEAM_SETUP_NONE;
}

static enum steam_setup_action steam_setup_observe( struct steam_setup_state *state, uintptr_t page,
                                                   enum steam_setup_action role, int ready,
                                                   int expected_directory, uint64_t now_ms )
{
    if (state->finished || !ready || !page || role == STEAM_SETUP_NONE) {
        state->page = 0;
        return STEAM_SETUP_NONE;
    }
    if (state->last_page == page && state->last_role == role) return STEAM_SETUP_NONE;
    if (state->page != page || state->role != role) {
        state->page = page; state->role = role; state->since_ms = now_ms;
        return STEAM_SETUP_NONE;
    }
    if (now_ms < state->since_ms || now_ms - state->since_ms < 700) return STEAM_SETUP_NONE;
    if (role == STEAM_SETUP_NEXT && state->next_count < 2 && !state->installing) return role;
    if (role == STEAM_SETUP_INSTALL && state->next_count == 2 && expected_directory && !state->installing) return role;
    if (role == STEAM_SETUP_FINISH && state->installing) return role;
    return STEAM_SETUP_NONE;
}

static void steam_setup_posted( struct steam_setup_state *state, enum steam_setup_action action )
{
    state->last_page = state->page; state->last_role = action;
    if (action == STEAM_SETUP_NEXT) state->next_count++;
    if (action == STEAM_SETUP_INSTALL) state->installing = 1;
    if (action == STEAM_SETUP_FINISH) state->finished = 1;
}
#endif
