#!/usr/bin/env bash
# Pin this tree as the SteamVR Desktop and keep Plasma as a separate entry.
# Run on the Frame, from the checkout that was live-tested (screens binary,
# patched aquamarine, and staged end-4 config). Does not modify ~/frametop-api.
#
#   session/install-hyprland-desktop.sh            # install files and entries
#   session/install-hyprland-desktop.sh --activate # also switch the running desktop
#
# FT_INSTALL_OFFLINE=1 skips systemd and is for the unit test.
# A failed --activate runs ~/.local/share/frametop/hyprland-desktop/rollback/latest/restore.sh.
set -euo pipefail
source=${FT_INSTALL_SOURCE:-$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)}
home=${FT_INSTALL_HOME:-$HOME}
offline=${FT_INSTALL_OFFLINE:-0}
activate=0
[ "${1:-}" = --activate ] && activate=1
pin=$home/.local/share/frametop/hyprland-desktop
plasma_session=${FT_PLASMA_SESSION:-$home/frametop-api/session/frametop-session.sh}
apps=$home/.local/share/applications
rollback=$pin/rollback/latest
previous_release=$(readlink -f "$pin/current" 2>/dev/null || true)
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}

die() { echo "frametop: $*" >&2; exit 1; }

case $pin in
  "$home/.local/share/frametop/hyprland-desktop") ;;
  *) die "refusing to install outside ~/.local/share/frametop/hyprland-desktop" ;;
esac
# The recovery desktop is the installed API tree. Never copy over it or from it.
case $source in
  "$home/frametop-api"|"$home/frametop-api"/*) die "refusing to install from frametop-api" ;;
esac
[ -x "$source/screens/build/ft-screens" ] || die "missing $source/screens/build/ft-screens"
[ -e "$source/build/aquamarine/lib64/libaquamarine.so.14" ] || [ -e "$source/build/aquamarine/lib/libaquamarine.so.14" ] || die "patched aquamarine is not built"
[ -f "$source/stage/config/quickshell/ii/shell.qml" ] || die "staged end-4 config is missing"
[ -f "$source/input/input-relay.py" ] || die "input relay is missing"

rev=${FT_INSTALL_REV:-$(git -C "$source" rev-parse --short=12 HEAD 2>/dev/null || true)}
[ -n "$rev" ] || rev=unversioned
release=$pin/releases/$rev
case $release in
  "$pin/releases/"*) ;;
  *) die "refusing release path $release" ;;
esac

copy_tree() {
  rm -rf "$release"
  mkdir -p "$release/scripts" "$release/screens/build" "$release/build"
  cp -a "$source/session" "$release/session"
  cp -a "$source/scripts/in-box" "$source/scripts/container-up.sh" "$release/scripts/"
  cp -a "$source/input" "$release/input"
  # Settings desktop entries in this session must resolve inside the release.
  for dir in display-settings input-settings remote-displays steam; do
    [ ! -d "$source/$dir" ] || cp -a "$source/$dir" "$release/$dir"
  done
  if [ -d "$source/gaze/probe" ]; then
    mkdir -p "$release/gaze"
    cp -a "$source/gaze/probe" "$release/gaze/"
  fi
  mkdir -p "$release/layout"
  cp -a "$source/layout/ft-layout" "$source/layout/ft_layout.py" \
    "$source/layout/ft-hide-show" "$source/layout/ft-layout-reset" "$release/layout/"
  chmod 755 "$release/layout/ft-layout" "$release/layout/ft-hide-show" "$release/layout/ft-layout-reset"
  cp -a "$source/screens/build/ft-screens" "$release/screens/build/ft-screens"
  if [ -d "$source/build/end4/bin" ]; then
    mkdir -p "$release/build/end4"
    cp -a "$source/build/end4/bin" "$release/build/end4/"
    if [ -d "$source/build/end4/lib64" ]; then
      cp -a "$source/build/end4/lib64" "$release/build/end4/"
    fi
  fi
  if [ -d "$source/build/aquamarine/lib64" ]; then
    cp -a "$source/build/aquamarine/lib64" "$release/build/aquamarine-lib"
    mkdir -p "$release/build/aquamarine"
    mv "$release/build/aquamarine-lib" "$release/build/aquamarine/lib64"
  else
    mkdir -p "$release/build/aquamarine"
    cp -a "$source/build/aquamarine/lib" "$release/build/aquamarine/lib"
  fi
  # Default tree path. The persistent copies below are what the session actually reads.
  mkdir -p "$release/stage"
  cp -a "$source/stage/config" "$release/stage/config"
  if [ -d "$source/stage/theme" ]; then
    cp -a "$source/stage/theme" "$release/stage/theme"
  fi
  cat > "$release/VERSION" <<EOF
commit=$rev
source=$source
installed=$(date -Is)
EOF
  ln -sfn "$release" "$pin/current"
}

save_rollback() {
  mkdir -p "$rollback/files"
  copy_if() {
    local src=$1 name=$2
    if [ -e "$src" ]; then
      cp -a "$src" "$rollback/files/$name"
      printf '%s\n' "$src" > "$rollback/files/$name.path"
    fi
  }
  copy_if "$apps/deckard-nested-desktop.desktop" deckard-nested-desktop.desktop
  copy_if "$apps/native-deckard-nested-desktop.desktop" native-deckard-nested-desktop.desktop
  copy_if "$home/.config/frametop.conf" frametop.conf
  copy_if "$home/.config/frametop-input.json" frametop-input.json
  copy_if "$home/.config/frametop-layout.json" frametop-layout.json
  copy_if "$home/.config/systemd/user/frametop-input-relay.service.d/hyprland.conf" hyprland.conf
  cat > "$rollback/restore.sh" <<EOF
#!/usr/bin/env bash
# Restore the desktop entry, input rules, and relay drop-in from this snapshot.
# Does not clear the input relay file-descriptor store.
set -eu
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=\$XDG_RUNTIME_DIR/bus
files=$rollback/files
restore_one() {
  local name=\$1 dest
  [ -f "\$files/\$name.path" ] || return 0
  dest=\$(cat "\$files/\$name.path")
  mkdir -p "\$(dirname "\$dest")"
  cp -a "\$files/\$name" "\$dest"
}
restore_one deckard-nested-desktop.desktop
restore_one native-deckard-nested-desktop.desktop
restore_one frametop.conf
restore_one frametop-input.json
restore_one frametop-layout.json
if [ -f "\$files/hyprland.conf.path" ]; then
  restore_one hyprland.conf
else
  rm -f "$home/.config/systemd/user/frametop-input-relay.service.d/hyprland.conf"
fi
mkdir -p "$home/.config/frametop"
printf '%s\n' plasma > "$home/.config/frametop/desktop-selection"
if [ "$offline" != 1 ]; then
  systemctl --user daemon-reload
  systemctl --user restart frametop-input-relay.service
  if [ -x "$pin/current/session/desktop-stop.sh" ]; then
    "$pin/current/session/desktop-stop.sh" || true
  fi
  if [ -x "$plasma_session" ]; then
    systemctl --user reset-failed frametop-desktop 2>/dev/null || true
    systemd-run --user --collect --quiet --unit frametop-desktop \\
      --setenv=FT_DESKTOP_SESSION=plasma \\
      "$plasma_session" || true
  fi
fi
echo "frametop: restored the previous desktop launcher and input relay"
EOF
  chmod 755 "$rollback/restore.sh"
}

install_entries() {
  mkdir -p "$apps" "$home/.local/bin" "$home/.config/frametop"
  cp -a "$release/session/frametop-desktop.sh" "$home/.local/bin/frametop-desktop"
  chmod 755 "$home/.local/bin/frametop-desktop"
  ln -sfn frametop-desktop "$home/.local/bin/frametop-plasma"
  sed "s|@SESSION@|$home/.local/bin/frametop-desktop|" \
    "$release/session/deckard-nested-desktop.desktop" > "$apps/deckard-nested-desktop.desktop"
  sed "s|@PLASMA_LAUNCHER@|$home/.local/bin/frametop-plasma|" \
    "$release/session/plasma-desktop.desktop" > "$apps/frametop-plasma-desktop.desktop"
  printf '%s\n' hyprland > "$home/.config/frametop/desktop-selection"
  # SteamVR's launch bar still starts these by name. Point them at this
  # release so Hide/Show Screens talks to the Hyprland compositor.
  for f in ft-screens-toggle ft-layout-reset; do
    if [ -f "$source/display-settings/$f.desktop" ]; then
      sed "s|@REPO@|$release|" "$source/display-settings/$f.desktop" > "$apps/$f.desktop"
    fi
  done
}

install_relay() {
  local drop=$home/.config/systemd/user/frametop-input-relay.service.d
  mkdir -p "$drop"
  cat > "$drop/hyprland.conf" <<EOF
[Service]
ExecStart=
ExecStart=/usr/bin/python3 $pin/current/input/input-relay.py
EOF
  python3 - "$home/.config/frametop-input.json" "$release/session/frame-controller-profile.json" <<'PY'
import json, sys
from pathlib import Path
rules_path, profile_path = Path(sys.argv[1]), Path(sys.argv[2])
profile = json.loads(profile_path.read_text(encoding="utf-8"))
if rules_path.is_file():
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
else:
    rules = {}
if not isinstance(rules, dict):
    raise SystemExit("frametop: input rules are not an object")
rules.setdefault("controller_chords", profile["controller_chords"])
rules.setdefault("controller_in_games", False)
rules_path.parent.mkdir(parents=True, exist_ok=True)
rules_path.write_text(json.dumps(rules, indent=2) + "\n", encoding="utf-8")
PY
}

seed_persistent() {
  # Config and fonts survive a later release. Seed each once.
  if [ ! -e "$pin/config/quickshell/ii/shell.qml" ]; then
    mkdir -p "$pin/config"
    cp -a "$source/stage/config/." "$pin/config/"
  fi
  # frame-theme.sh reads fonts from the directory beside this config.
  # Leave an existing theme alone so a later install does not replace a wallpaper.
  if [ ! -d "$pin/theme/fonts" ] && [ -d "$source/stage/theme/fonts" ]; then
    mkdir -p "$pin/theme"
    cp -a "$source/stage/theme/fonts" "$pin/theme/fonts"
  fi
}

copy_tree
seed_persistent
save_rollback
install_entries
if [ "$offline" != 1 ]; then
  install_relay
fi
echo "frametop: installed Hyprland $rev at $release"

if [ "$activate" != 1 ]; then
  exit 0
fi
[ "$offline" != 1 ] || die "--activate is not used offline"

fds_before=$(systemctl --user show -p NFileDescriptorStore --value frametop-input-relay.service 2>/dev/null || echo 0)
systemctl --user daemon-reload
systemctl --user restart frametop-input-relay.service
fds_after=$(systemctl --user show -p NFileDescriptorStore --value frametop-input-relay.service 2>/dev/null || echo 0)
if [ "${fds_before:-0}" != 0 ] && [ "${fds_after:-0}" = 0 ]; then
  echo "frametop: relay restart dropped the fd store ($fds_before -> 0); restoring" >&2
  "$rollback/restore.sh" || true
  exit 1
fi
# Stop the old release by its own path before starting the new one. Its
# cleanup matches that path and must run before the new compositor exists.
if [ -n "$previous_release" ] && [ "$previous_release" != "$release" ] &&
   [ -x "$previous_release/session/desktop-stop.sh" ]; then
  "$previous_release/session/desktop-stop.sh" || true
fi
"$pin/current/session/desktop-stop.sh" || true
sleep 1
if ! "$home/.local/bin/frametop-desktop" use hyprland; then
  echo "frametop: Hyprland did not start; restoring Plasma" >&2
  "$rollback/restore.sh" || true
  exit 1
fi
ok=0
for _ in $(seq 150); do
  if [ -S "$XDG_RUNTIME_DIR/ft-hyprland-0" ]; then ok=1; break; fi
  sleep 0.2
done
if [ "$ok" != 1 ]; then
  echo "frametop: Hyprland panel socket did not appear; restoring Plasma" >&2
  "$rollback/restore.sh" || true
  exit 1
fi
echo "frametop: Hyprland is the running desktop (fdstore $fds_before -> $fds_after)"
