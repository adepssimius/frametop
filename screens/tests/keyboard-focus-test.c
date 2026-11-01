#include <assert.h>
#include "../keyboard-focus.h"

int main(void) {
    assert(ft_desktop_keyboard_wanted(1, 0, 1, 0));
    assert(ft_desktop_keyboard_wanted(0, 1, 1, 0));
    assert(!ft_desktop_keyboard_wanted(0, 0, 1, 0));
    assert(!ft_desktop_keyboard_wanted(0, 1, 0, 0));
    assert(!ft_desktop_keyboard_wanted(0, 1, 1, 1));
    return 0;
}
