#!/usr/bin/env bash
# Services for the staged end-4 startup, confined to this Wayland session.
set -u
here=$(dirname "$(readlink -f "$0")")
# The official Tailscale tray needs the desktop's private D-Bus, so start it
# here rather than on the user's systemd bus. It is optional and installed
# independently of Frametop.
if [ "${FT_NO_VR_SMOKE:-}" != 1 ] && [ -f "$HOME/.config/autostart/tailscale-systray.desktop" ] && \
   [ -x "$HOME/.local/bin/tailscale" ]; then
  if [ -S /run/host/run/tailscale/tailscaled.sock ]; then
    setsid "$HOME/.local/bin/tailscale" --socket=/run/host/run/tailscale/tailscaled.sock systray >/dev/null 2>&1 < /dev/null &
  else
    setsid "$HOME/.local/bin/tailscale" systray >/dev/null 2>&1 < /dev/null &
  fi
fi
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
