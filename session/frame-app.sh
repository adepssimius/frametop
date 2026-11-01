#!/bin/sh
# An app keybind from the staged Hyprland config. Those commands point at
# ~/.config/hypr on the laptop. Here they run inside the Fedora container,
# and a missing program is reported instead of looking like a dead key.
set -u
action=${1:-}
say() { echo "frametop: $*" >&2; }

launch_first() {
    here=$(dirname "$(readlink -f "$0")")
    looked=$*
    for spec in "$@"; do
        # shellcheck disable=SC2086
        set -- $spec
        if command -v "$1" >/dev/null 2>&1; then
            exec "$@"
        fi
    done
    say "nothing installed for $action ($looked)"
    # shellcheck disable=SC2086
    exec foot "$here/frame-missing.sh" "$action" $looked
}

case "$action" in
    terminal) launch_first kitty foot alacritty ;;
    files) launch_first dolphin nautilus nemo thunar ;;
    browser) launch_first google-chrome-stable firefox chromium ;;
    *)
        say "unknown app $action"
        exit 1
        ;;
esac
