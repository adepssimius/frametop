#!/usr/bin/env bash
# One desktop action for a controller chord or for a test.
# The host relay runs this script. Hyprland, qs, and the apps live in the
# Fedora container, so the first step only reads the session route and
# re-enters there. The route names one runtime directory.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
action=${1:-}

# This Hyprland is configured in Lua. `hyprctl dispatch workspace r+1` is parsed
# as Lua and rejected. hl.dispatch is the call that actually runs.
hypr_eval() {
  hyprctl eval "$1"
}

launch_first() {
  local cmd
  for cmd in "$@"; do
    [ -n "$cmd" ] || continue
    # shellcheck disable=SC2086
    command -v ${cmd%% *} >/dev/null 2>&1 || continue
    # Hyprland owns the process. A program started by this short-lived
    # container command would exit with it.
    hypr_eval "hl.dispatch(hl.dsp.exec_cmd(\"$cmd\"))"
    return
  done
  echo "frametop: none of these commands are installed: $*" >&2
  hypr_eval "hl.dispatch(hl.dsp.exec_cmd(\"foot $here/frame-missing.sh $action $*\"))"
}

if [ "${FT_DESKTOP_INNER:-}" != 1 ]; then
  route=${FT_HYPR_ROUTE:-${XDG_RUNTIME_DIR:-}/frametop-hyprland.route}
  if [ ! -f "$route" ]; then
    echo "frametop: no experimental Hyprland session route ($route)" >&2
    exit 2
  fi
  exported=$(python3 "$here/../input/desktop_route.py" --export "$route") || exit $?
  # shellcheck disable=SC1090
  eval "$exported"
  # The session keeps frame-desktopd.py in the container. A press then costs
  # one socket write instead of a new container entry.
  desktop_sock=$FT_ROUTE_RUNTIME/frametop-desktop.sock
  if [ -S "$desktop_sock" ]; then
    set +e
    python3 "$here/frame-desktopd.py" --send "$desktop_sock" "$action"
    status=$?
    set -e
    if [ "$status" -ne 111 ]; then
      exit "$status"
    fi
  fi
  runner=$here/../scripts/in-box
  if [ -n "${FT_DESKTOP_RUNNER:-}" ]; then
    runner=$FT_DESKTOP_RUNNER
  fi
  exec "$runner" env \
    XDG_RUNTIME_DIR="$FT_ROUTE_RUNTIME" \
    HYPRLAND_INSTANCE_SIGNATURE="$FT_ROUTE_SIGNATURE" \
    XDG_CONFIG_HOME="$FT_ROUTE_CONFIG_HOME" \
    WAYLAND_DISPLAY="$FT_ROUTE_WAYLAND" \
    FT_DESKTOP_INNER=1 \
    "$0" "$action"
fi

case $action in
  workspace-prev) hypr_eval 'hl.dispatch(hl.dsp.focus({ workspace = "r-1" }))' ;;
  workspace-next) hypr_eval 'hl.dispatch(hl.dsp.focus({ workspace = "r+1" }))' ;;
  window-prev) hypr_eval 'hl.dispatch(hl.dsp.window.move({ workspace = "r-1", follow = false }))' ;;
  window-next) hypr_eval 'hl.dispatch(hl.dsp.window.move({ workspace = "r+1", follow = false }))' ;;
  close) hypr_eval 'hl.dispatch(hl.dsp.window.close())' ;;
  terminal)
    launch_first kitty foot alacritty wezterm konsole kgx uxterm xterm
    ;;
  files)
    launch_first dolphin nautilus nemo thunar "kitty -1 fish -c yazi"
    ;;
  browser)
    launch_first google-chrome-stable zen-browser firefox brave chromium microsoft-edge-stable opera librewolf
    ;;
  launcher)
    if ! command -v qs >/dev/null 2>&1; then
      echo "frametop: qs is not installed; the end-4 launcher was not opened" >&2
      exit 0
    fi
    timeout 2s qs -c "${FT_QS_CONFIG:-ii}" ipc call search toggle
    ;;
  *)
    echo "frametop: unknown desktop action: ${action:-<none>}" >&2
    exit 2
    ;;
esac
