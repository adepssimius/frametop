#!/usr/bin/env bash
# Start the existing end-4 Quickshell. A missing binary or config exits 0 so
# Hyprland keeps running. This process is not the compositor.
set -u
here=$(dirname "$(readlink -f "$0")")
cfg=${FT_QS_CONFIG:-ii}
config_home=${FT_USER_CONFIG_HOME:-$HOME/.config}
shell=$config_home/quickshell/$cfg/shell.qml
# Older installed stages need the same session-scoped process handling.
if [ -f "$shell" ]; then
  python3 "$here/stage-end4.py" --prepare-session "$config_home" || exit 1
fi
export XDG_CONFIG_HOME=$config_home
# The session's XDG_DATA_HOME is a Frametop directory, so the launcher does not
# see the normal application directories. The host image comes first: the
# copy of Steam in ~/.local/share is marked hidden and would otherwise cover
# the visible one. Frametop settings and installed games still come from
# ~/.local/share, which has no host copy of those names.
# Shadow the host's older Plasma launchers only in this nested session. The
# private runtime disappears with the session and leaves Plasma's entries alone.
entry_dir=${XDG_RUNTIME_DIR:?}/frametop-apps/applications
mkdir -p "$entry_dir"
for app in display-settings/ft-display-settings input-settings/ft-input-settings \
           remote-displays/ft-remote-displays; do
  name=${app##*/}
  template=$here/../$app.desktop
  if [ -f "$template" ] && [ -x "$here/../$app" ]; then
    sed "s|@REPO@|$here/..|g" "$template" > "$entry_dir/$name.desktop"
  fi
done
export XDG_DATA_DIRS="$XDG_RUNTIME_DIR/frametop-apps:/run/host/usr/share:$HOME/.local/share${XDG_DATA_DIRS:+:$XDG_DATA_DIRS}"
if [ -f "$shell" ] && [ -x "$here/frame-theme.sh" ]; then
  theme_env=$("$here/frame-theme.sh" "$config_home" || true)
  if [ -n "${theme_env:-}" ]; then
    # shellcheck disable=SC2086
    eval "$theme_env"
    if [ -n "${FONTCONFIG_FILE:-}" ]; then
      export FONTCONFIG_FILE
    fi
    if [ -n "${FT_FRAME_FONT_MATERIAL:-}" ]; then
      export FT_FRAME_FONT_MATERIAL
    fi
  fi
fi
if ! command -v qs >/dev/null 2>&1; then
  echo "frametop: qs is not installed; continuing without Quickshell" >&2
  exit 0
fi
if [ ! -f "$shell" ]; then
  echo "frametop: Quickshell config $shell is not on this machine; continuing without it" >&2
  exit 0
fi
# cliphist list exits 1 until the database has an entry. Seed it before
# the shell's first refresh. The watcher lives in hyprland-on-start.sh.
if command -v cliphist >/dev/null 2>&1; then
  printf ' ' | cliphist store >/dev/null 2>&1 || true
fi
if [ -n "${FT_QS_LOG:-}" ]; then
  exec qs -c "$cfg" >"$FT_QS_LOG" 2>&1
fi
exec qs -c "$cfg"
