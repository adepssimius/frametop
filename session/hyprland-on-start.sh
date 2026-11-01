#!/usr/bin/env bash
# Runs only inside the nested Hyprland process environment (never on SteamOS).
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
# FT_HYPR_OUTPUTS is the number of Hyprland monitors. FT_SCREEN_COUNT is the
# ft-screens slot count, which can be higher when a slot is unused.
count=${FT_HYPR_OUTPUTS:-${FT_SCREEN_COUNT:-1}}
if ! [[ $count =~ ^[1-9][0-9]*$ ]] || (( count > 24 )); then
  echo "frametop: invalid FT_SCREEN_COUNT for output startup: $count" >&2
  exit 2
fi
if ! command -v hyprctl >/dev/null 2>&1; then
  echo "frametop: missing hyprctl in nested Hyprland environment" >&2
  exit 1
fi
# Aquamarine already creates output 1. Each added Wayland-backed output opens
# another host xdg_toplevel that ft-screens can map to a VR panel.
for ((i = 1; i < count; i++)); do
  if ! hyprctl output create wayland; then
    echo "frametop: unable to create Wayland output $((i + 1))" >&2
    exit 1
  fi
done
# cliphist list fails until one item has been stored. The watcher then
# keeps this session's clipboard. Both exit when the Wayland socket does.
if command -v cliphist >/dev/null 2>&1; then
  printf ' ' | cliphist store >/dev/null 2>&1 || true
fi
if command -v cliphist >/dev/null 2>&1 && command -v wl-paste >/dev/null 2>&1; then
  setsid wl-paste --watch cliphist store >/dev/null 2>&1 < /dev/null &
fi
# Stay up for the life of this runtime. Controller presses talk to it
# instead of starting a container for each button.
if [ -n "${XDG_RUNTIME_DIR:-}" ] && [ ! -S "$XDG_RUNTIME_DIR/frametop-desktop.sock" ]; then
  setsid python3 "$here/frame-desktopd.py" "$XDG_RUNTIME_DIR/frametop-desktop.sock" \
    >/dev/null 2>&1 < /dev/null &
fi
# The profile this desktop starts in reopens its windows. Screen places
# already came from the layout. This does not restart SteamVR.
if [ -f "$here/hyprland_profile.py" ]; then
  setsid python3 "$here/hyprland_profile.py" start >/dev/null 2>&1 < /dev/null &
fi
if command -v foot >/dev/null 2>&1; then
  exec foot
elif command -v kitty >/dev/null 2>&1; then
  exec kitty
fi
echo "frametop: no foot or kitty installed; nested compositor remains available" >&2
