#pragma once

/* A display remains the typing target after the pointer leaves. Visibility
 * and Steam's dashboard always take precedence over the remembered target. */
static inline int ft_desktop_keyboard_wanted(int pointed, int last_desktop,
                                              int screens_shown, int steam_front) {
    return (pointed || last_desktop) && screens_shown && !steam_front;
}
