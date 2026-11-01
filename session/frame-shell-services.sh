#!/usr/bin/env bash
# Services for the staged end-4 startup, confined to this Wayland session.
set -u
here=$(dirname "$(readlink -f "$0")")
if command -v cliphist >/dev/null 2>&1 && command -v wl-paste >/dev/null 2>&1; then
  setsid wl-paste --watch cliphist store >/dev/null 2>&1 < /dev/null &
fi
if [ "${FT_NO_VR_SMOKE:-}" != 1 ] && [ -x "$here/../input/ft-hypr-textinput" ]; then
  setsid "$here/../input/ft-hypr-textinput" >"${XDG_RUNTIME_DIR:-/tmp}/frametop-textinput.log" 2>&1 < /dev/null &
fi
if [ "${FT_NO_VR_SMOKE:-}" != 1 ] && [ -f "$here/hyprland_profile.py" ]; then
  (
    # Wait for the output helper to assign monitors before restoring windows.
    for _ in {1..30}; do
      [ -s "${XDG_RUNTIME_DIR:-}/frametop-output-map.json" ] && break
      sleep 0.5
    done
    exec python3 "$here/hyprland_profile.py" start
  ) >/dev/null 2>&1 < /dev/null &
fi
