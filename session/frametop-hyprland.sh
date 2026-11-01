#!/usr/bin/env bash
# Experimental nested Hyprland session. Invoked only by frametop-session.sh --inner.
# Keep everything Hyprland-specific here, rather than changing the working KWin path.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")

# ft-screens is the Wayland parent, not a physical DRM/KMS device. The absolute
# path stays valid after we give Hyprland its own XDG_RUNTIME_DIR for its sockets.
parent_wayland=${WAYLAND_DISPLAY:-}
if [[ $parent_wayland != /* || ! -S $parent_wayland ]]; then
  echo "frametop: Hyprland needs the absolute ft-screens Wayland socket" >&2
  exit 2
fi

count=${FT_SCREEN_COUNT:-1}
if ! [[ $count =~ ^[1-9][0-9]*$ ]] || (( count > 24 )); then
  echo "frametop: invalid FT_SCREEN_COUNT: $count" >&2
  exit 2
fi

config=${FT_HYPRLAND_CONFIG:-$here/hyprland-frame.lua}
if [ ! -f "$config" ]; then
  echo "frametop: Hyprland configuration not found: $config" >&2
  exit 2
fi

# Host is immutable SteamOS; source builds and optional Hyprland installation
# live in the Fedora dev container. in-box starts that container before entering
# it, so do not change the wrapper's own runtime before calling it.
# shellcheck disable=SC1091
. "$here/hyprland-env.sh"
frametop_prepend_aquamarine "$here/.."
: "${XDG_RUNTIME_DIR:?}"
# Hyprland's socket is $XDG_RUNTIME_DIR/hypr/<abi signature>/.socket2.sock.
# sun_path holds 108 bytes; nesting it under the user runtime directory overflows it and
# Hyprland turns IPC off, so startup cannot add outputs.
runtime=$(mktemp -d /tmp/ftH.XXXXXX)
config_home=${FT_USER_CONFIG_HOME:-$(readlink -f "$here/../stage/config")}
hypr_root=${FT_HYPR_CONFIG_ROOT:-$config_home/hypr}
if [ -d "$config_home" ]; then config_home=$(readlink -f "$config_home"); fi
if [ -d "$hypr_root" ]; then hypr_root=$(readlink -f "$hypr_root"); fi
cleanup() {
  trap - EXIT INT TERM
  frametop_hyprland_route_end || true
  rm -rf -- "$runtime"
}
trap cleanup EXIT
trap 'cleanup; exit 143' INT TERM
frametop_hyprland_route_begin "$runtime" "$parent_wayland" "$config_home"
mkdir -p "$HOME/.config/frametop/hyprland" "$HOME/.local/state/frametop/hyprland" \
  "$HOME/.local/share/frametop/hyprland"
# The host runtime is replaced below so Hyprland's socket fits in sun_path.
# PipeWire and Pulse stay on that host runtime; this does not start a second server.
host_runtime=$XDG_RUNTIME_DIR
PIPEWIRE_RUNTIME_DIR=
PULSE_SERVER=
if [ -S "$host_runtime/pipewire-0" ]; then PIPEWIRE_RUNTIME_DIR=$host_runtime; fi
if [ -S "$host_runtime/pulse/native" ]; then PULSE_SERVER=unix:$host_runtime/pulse/native; fi
# An alongside session keeps its generated colors away from the installed
# desktop. The installed session still uses the shared Hyprland state.
if [ -n "${FT_HYPRLAND_ALONGSIDE:-}" ]; then
  state_home=$HOME/.local/state/frametop/hyprland-exp
else
  state_home=$HOME/.local/state/frametop/hyprland
fi
mkdir -p "$state_home"
export XDG_STATE_HOME="$state_home"
export FT_USER_CONFIG_HOME="$config_home"
export FT_APP_CONFIG_HOME="$HOME/.config/frametop/hyprland"
export FT_APP_DATA_HOME="$HOME/.local/share/frametop/hyprland"
theme_env=$("$here/frame-theme.sh" "$config_home" || true)
if [ -n "${theme_env:-}" ]; then
  # shellcheck disable=SC2086
  eval "$theme_env"
fi

# Disabling Hyprland's systemd/DBus activation-environment imports prevents the
# nested compositor from redirecting SteamOS's own services into this session.
# dbus-run-session runs *inside* the container with the isolated session's env.
# Quickshell is started by the Frame config when the laptop's end-4 tree is present.
# It is a client: its exit does not stop Hyprland. hypridle and suspend stay off.
echo "frametop: starting experimental nested Hyprland ($count panel(s))" >&2
launch=(env -u HYPRLAND_INSTANCE_SIGNATURE
  LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"
  XDG_RUNTIME_DIR="$runtime"
  WAYLAND_DISPLAY="$parent_wayland"
  XDG_CONFIG_HOME="$HOME/.config/frametop/hyprland"
  XDG_STATE_HOME="$state_home"
  XDG_DATA_HOME="$HOME/.local/share/frametop/hyprland"
  XDG_CURRENT_DESKTOP=Hyprland
  QT_QPA_PLATFORMTHEME=kde
  XDG_SESSION_DESKTOP=Hyprland
  XDG_SESSION_TYPE=wayland
  HYPRLAND_NO_SD_VARS=1
  HYPRLAND_NO_SD_NOTIFY=1
  HYPRLAND_NO_SD_TARGET=1
  FT_SCREEN_COUNT="$count"
  FT_HYPR_OUTPUTS="${FT_HYPR_OUTPUTS:-$count}"
  FT_OUTPUT_NAMES="${FT_OUTPUT_NAMES:-1}"
  FT_HYPR_CONTROL="${FT_HYPR_CONTROL:-${FT_HYPRLAND_CONTROL:-ft_hyprland}}"
  FT_HOST_RUNTIME="$host_runtime"
  FT_HYPRLAND_STARTUP="$here/hyprland-on-start.sh"
  FT_FRAME_SESSION="$here"
  FT_USER_CONFIG_HOME="$config_home"
  FT_APP_CONFIG_HOME="$HOME/.config/frametop/hyprland"
  FT_APP_DATA_HOME="$HOME/.local/share/frametop/hyprland"
  FT_HYPR_CONFIG_ROOT="$hypr_root"
  PATH="$here/../build/end4/bin:$here/bin:${PATH:-/usr/local/bin:/usr/bin}")
if [ -n "$PIPEWIRE_RUNTIME_DIR" ]; then launch+=(PIPEWIRE_RUNTIME_DIR="$PIPEWIRE_RUNTIME_DIR"); fi
if [ -n "$PULSE_SERVER" ]; then launch+=(PULSE_SERVER="$PULSE_SERVER"); fi
if [ -n "${FONTCONFIG_FILE:-}" ]; then launch+=(FONTCONFIG_FILE="$FONTCONFIG_FILE"); fi
launch+=(dbus-run-session Hyprland -c "$config")
"$here/../scripts/in-box" "${launch[@]}"
