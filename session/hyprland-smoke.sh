#!/usr/bin/env bash
# Isolated protocol/output smoke-test: NO SteamVR panels, no running session changes.
# Runs ft-screens --no-vr on unique sockets and a temporary Hyprland session.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
root=$(readlink -f "$here/..")
duration=${FT_HYPRLAND_SMOKE_SECONDS:-15}
count=${FT_SCREEN_COUNT:-1}
if ! [[ $duration =~ ^[0-9]+$ ]] || (( duration < 5 || duration > 60 )); then
  echo "frametop: smoke duration must be an integer 5..60 seconds" >&2
  exit 2
fi
if ! [[ $count =~ ^[1-9][0-9]*$ ]] || (( count > 4 )); then
  echo "frametop: smoke screen count must be 1..4" >&2
  exit 2
fi

if [ "${1:-}" = --inner ]; then
  if [[ ${WAYLAND_DISPLAY:-} != /* || ! -S $WAYLAND_DISPLAY ]]; then
    echo "frametop: smoke inner needs ft-screens' absolute Wayland socket" >&2
    exit 2
  fi
  # A fresh directory, config and state: no edits to either host or Frametop
  # profiles. Closing this child makes ft-screens terminate via SIGCHLD.
  # Check the actual advertised protocols before moving XDG_RUNTIME_DIR.
  # Aquamarine 0.15.1 binds these exact versions, not lower fallbacks.
  if ! command -v wayland-info >/dev/null 2>&1; then
    echo "frametop: wayland-info required for smoke protocol audit" >&2
    exit 1
  fi
  wayland-info | python3 "$here/hyprland-protocol-check.py"
  # Hyprland's socket is $XDG_RUNTIME_DIR/hypr/<abi signature>/.socket2.sock.
  # sun_path holds 108 bytes; nesting it under the user runtime directory overflows it and
  # Hyprland turns IPC off, so startup cannot add outputs.
  host_runtime=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
  runtime=$(mktemp -d /tmp/ftH.XXXXXX)
  trap 'rm -rf -- "$runtime" || true' EXIT
  mkdir -p "$runtime/config" "$runtime/state"
  export XDG_RUNTIME_DIR="$runtime"
  if [ -S "$host_runtime/pipewire-0" ]; then export PIPEWIRE_RUNTIME_DIR=$host_runtime; fi
  if [ -S "$host_runtime/pulse/native" ]; then export PULSE_SERVER=unix:$host_runtime/pulse/native; fi
  export PATH="$root/build/end4/bin:$here/bin:${PATH:-/usr/bin}"
  export XDG_CONFIG_HOME="$runtime/config/frametop"
  export XDG_STATE_HOME="$runtime/state"
  export XDG_DATA_HOME="$runtime/data"
  export FT_APP_CONFIG_HOME="$XDG_CONFIG_HOME"
  export FT_APP_DATA_HOME="$runtime/data"
  export FT_HYPRLAND_LAYOUT="$runtime/layout.json"
  export FT_NO_VR_SMOKE=1
  mkdir -p "$XDG_CONFIG_HOME" "$XDG_DATA_HOME"
  export XDG_CURRENT_DESKTOP=Hyprland XDG_SESSION_TYPE=wayland XDG_SESSION_DESKTOP=Hyprland
  export QT_QPA_PLATFORMTHEME=kde
  export HYPRLAND_NO_SD_VARS=1 HYPRLAND_NO_SD_NOTIFY=1 HYPRLAND_NO_SD_TARGET=1
  export FT_HYPRLAND_STARTUP="$here/hyprland-on-start.sh"
  export FT_FRAME_SESSION="${FT_FRAME_SESSION:-$here}"
  # shellcheck disable=SC1091
  . "$here/hyprland-env.sh"
  if [ "${FT_APP_PROBE:-}" = 1 ]; then
    (
      sleep 6
      sig=$(find "$XDG_RUNTIME_DIR/hypr" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | head -n 1 || true)
      report=/tmp/ft-app-probe.txt
      {
        echo "signature=$sig"
        if [ -n "$sig" ]; then
          export HYPRLAND_INSTANCE_SIGNATURE=$sig FT_DESKTOP_INNER=1
          echo "terminal:"
          "$here/frame-desktop-action.sh" terminal || true
          if [ "${FT_LAUNCHER_STRESS:-}" = 1 ]; then
            for _ in 1 2 3 4 5 6 7; do
              hyprctl eval 'hl.dispatch(hl.dsp.exec_cmd("kitty"))' || true
            done
          fi
          echo "display-settings:"
          hyprctl eval "hl.dispatch(hl.dsp.exec_cmd(\"$root/display-settings/ft-display-settings\"))" || true
          echo "input-settings:"
          hyprctl eval "hl.dispatch(hl.dsp.exec_cmd(\"$root/input-settings/ft-input-settings\"))" || true
          echo "action-files:"
          "$here/frame-desktop-action.sh" files || true
          echo "action-browser:"
          "$here/frame-desktop-action.sh" browser || true
          sleep 12
          if command -v hyprsunset >/dev/null 2>&1; then
            inner_display=$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -type s -name "wayland-*" -printf "%f\n" | head -n 1)
            WAYLAND_DISPLAY="$inner_display" hyprsunset >"$XDG_RUNTIME_DIR/hyprsunset.log" 2>&1 &
            sunset_pid=$!
            sleep 2
            echo "hyprsunset-status:"
            hyprctl hyprsunset temperature || true
            kill "$sunset_pid" 2>/dev/null || true
            wait "$sunset_pid" 2>/dev/null || true
            cat "$XDG_RUNTIME_DIR/hyprsunset.log"
          fi
          echo "clients:"
          hyprctl clients || true
          kitty_pid=$(hyprctl clients -j | python3 -c 'import json,sys; c=json.load(sys.stdin); print(next((str(x["pid"]) for x in c if x.get("class")=="kitty"), ""))')
          if [ -n "$kitty_pid" ] && pgrep -P "$kitty_pid" -x fish >/dev/null; then
            echo "kitty-fish=ok"
          else
            echo "kitty-fish=missing"
          fi
        fi
      } >"$report" 2>&1
    ) &
    app_probe=$!
  fi
  if [ "${FT_QS_SMOKE:-}" = 1 ]; then
    report=/tmp/ft-qs-smoke-report.txt
    : > "$report"
    (
      sleep 8
      {
        echo "qs=$(command -v qs || true)"
        qs --version 2>&1 || true
        sigs=$(find "$XDG_RUNTIME_DIR/hypr" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null || true)
        echo "signatures<<EOF"
        printf '%s\n' "$sigs"
        echo "EOF"
        sig=$(printf '%s\n' "$sigs" | head -n 1)
        count=$(printf '%s\n' "$sigs" | sed '/^$/d' | wc -l)
        echo "signature_count=$count"
        if [ "$count" -eq 1 ] && [ -n "$sig" ]; then
          HYPRLAND_INSTANCE_SIGNATURE=$sig hyprctl version 2>&1 | head -n 3 || true
          echo "bind_lines=$(HYPRLAND_INSTANCE_SIGNATURE=$sig hyprctl binds 2>/dev/null | wc -l)"
        fi
        if [ "${FT_IME_PROBE:-}" = 1 ]; then
          inner_display=$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -type s -name "wayland-*" -printf "%f\n" | head -n 1)
          set +e
          timeout 3s env WAYLAND_DISPLAY="$inner_display" FT_TEXTINPUT_RELAY=frametop_smoke_unused "$root/input/ft-hypr-textinput" >"$report.ime" 2>&1
          ime_status=$?
          set -e
          echo "ime_status=$ime_status"
          cat "$report.ime"
        fi
        if command -v qs >/dev/null 2>&1; then
          XDG_CONFIG_HOME="${FT_USER_CONFIG_HOME:-$XDG_CONFIG_HOME}" qs -c "${FT_QS_CONFIG:-ii}" list --any-display >"$report.list" 2>&1 || true
          echo "instances<<"
          cat "$report.list" 2>/dev/null || true
          echo ">>"
          if timeout 3s env XDG_CONFIG_HOME="${FT_USER_CONFIG_HOME:-$XDG_CONFIG_HOME}" qs -c "${FT_QS_CONFIG:-ii}" ipc call search toggle >"$report.ipc" 2>&1; then
            echo "ipc_status=0"
          else
            status=$?
            echo "ipc_status=$status"
          fi
          sleep 2
          if timeout 3s env XDG_CONFIG_HOME="${FT_USER_CONFIG_HOME:-$XDG_CONFIG_HOME}" qs -c "${FT_QS_CONFIG:-ii}" ipc call search close >/dev/null 2>&1; then
            echo "launcher-responsive=1"
          else
            echo "launcher-responsive=0"
          fi
          echo "ipc<<"
          cat "$report.ipc" 2>/dev/null || true
          echo ">>"
        fi
        pgrep -a qs || echo "qs-not-running"
      } >> "$report" 2>&1
    ) &
    probe=$!
  fi
  frametop_prepend_aquamarine "$root"
  config=${FT_HYPRLAND_CONFIG:-$here/hyprland-minimal.lua}
  echo "frametop: smoke running Hyprland for ${duration}s; safe timeout is expected" >&2
  # Sample commits while Hyprland is still mapped. A query after it exits sees
  # no toplevels: destroying the client closes them before this script continues.
  if [ -n "${FT_HYPR_CONTROL:-}" ]; then
    (
      sleep $((duration - 2))
      python3 - "$FT_HYPR_CONTROL" << 'PY'
import socket, sys
sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
sock.bind("")
sock.settimeout(2)
sock.sendto(b"toplevels", b"\0" + sys.argv[1].encode())
text = sock.recv(8192).decode()
sys.stdout.write(text if text.endswith("\n") else text + "\n")
PY
    ) &
    query=$!
  fi
  set +e
  timeout --signal=TERM --kill-after=5s "${duration}s" dbus-run-session Hyprland -c "$config"
  result=$?
  set -e
  if [ -n "${query:-}" ]; then
    wait "$query" || true
  fi
  if [ -n "${probe:-}" ]; then
    wait "$probe" || true
  fi
  if [ -n "${app_probe:-}" ]; then
    wait "$app_probe" || true
  fi
  logf=$(find "$runtime" -name hyprland.log -print -quit 2>/dev/null || true)
  if [ -n "$logf" ]; then
    echo "frametop: hyprland log excerpts"
    grep -E "ERR|error|Output |failed|dmabuf|DMA" "$logf" | head -80 || true
  fi
  if (( result == 124 )); then
    echo "frametop: smoke finished at safety timeout (expected)" >&2
    exit 0
  fi
  exit "$result"
fi

if (( $# != 0 )); then
  echo "Usage: FT_SCREEN_COUNT=1 $0" >&2
  exit 2
fi
# No default ft_screens/ft-screens-0 sockets. Never kill another instance.
# This must be launched in the container with the branch's ft-screens build.
# A timeout alone is not success: Aquamarine can stay up after wlroots rejects
# its first buffer, and ft-screens exits 0 when that child ends.
width=1280
height=720
screens=()
for ((i = 0; i < count; i++)); do
  screens+=(--screen "${width}x${height}@1.0")
done
sock="ft-hypr-smoke-$$"
ctl="ft_hypr_smoke_$$"
echo "frametop: isolated --no-vr smoke; socket $sock, control $ctl, $count output(s)" >&2
log=$(mktemp)
trap 'rm -f "$log"' EXIT
pass=()
if [ "${FT_QS_SMOKE:-}" = 1 ]; then
  export FT_FRAME_SESSION="${FT_FRAME_SESSION:-$here}"
  export FT_HYPRLAND_CONFIG="${FT_HYPRLAND_CONFIG:-$here/hyprland-frame.lua}"
fi
  for key in FT_HYPRLAND_CONFIG FT_USER_CONFIG_HOME FT_HYPR_CONFIG_ROOT FT_FRAME_SESSION FT_QS_SMOKE FT_QS_CONFIG FT_QS_LOG FT_APP_PROBE FT_LAUNCHER_STRESS FT_IME_PROBE; do
  if [ -n "${!key:-}" ]; then
    pass+=("$key=${!key}")
  fi
done
set +e
"$root/scripts/in-box" "$root/screens/build/ft-screens" --no-vr \
  --socket "$sock" --control "$ctl" "${screens[@]}" -- env "${pass[@]}" FT_SCREEN_COUNT="$count" FT_HYPR_CONTROL="$ctl" FT_HYPRLAND_SMOKE_SECONDS="$duration" "$0" --inner \
  >"$log" 2>&1
status=$?
set -e
cat "$log" >&2
probe_errors=0
if [ "${FT_APP_PROBE:-}" = 1 ]; then
  if [ -f /tmp/ft-app-probe.txt ]; then
    echo "frametop: app probe" >&2
    cat /tmp/ft-app-probe.txt >&2
    if ! grep -Fx "kitty-fish=ok" /tmp/ft-app-probe.txt >/dev/null; then
      echo "frametop: Kitty did not start Fish" >&2
      probe_errors=1
    fi
    for app in kitty ft-display-settings ft-input-settings; do
      if ! grep -F "class: $app" /tmp/ft-app-probe.txt >/dev/null; then
        echo "frametop: app probe missing $app window" >&2
        probe_errors=1
      fi
    done
    rm -f /tmp/ft-app-probe.txt
  else
    echo "frametop: missing app probe report" >&2
    probe_errors=1
  fi
fi
if [ -f /tmp/ft-qs-smoke-report.txt ]; then
  echo "frametop: quickshell smoke report" >&2
  cat /tmp/ft-qs-smoke-report.txt >&2
  if [ "${FT_IME_PROBE:-}" = 1 ] && ! grep -Fx 'ime_status=124' /tmp/ft-qs-smoke-report.txt >/dev/null; then
    echo "frametop: input-method probe exited unexpectedly" >&2
    probe_errors=1
  fi
  rm -f /tmp/ft-qs-smoke-report.txt /tmp/ft-qs-smoke-report.txt.ipc
elif [ "${FT_IME_PROBE:-}" = 1 ]; then
  echo "frametop: missing input-method probe report" >&2
  probe_errors=1
fi
if [ -f "${FT_QS_LOG:-}" ]; then
  echo "frametop: quickshell log" >&2
  cat "$FT_QS_LOG" >&2
fi
errors=$probe_errors
if (( status != 0 )); then
  echo "frametop: smoke process exited $status" >&2
  errors=1
fi
if ! grep -F "Frametop Wayland protocol version preflight: PASS" "$log" >/dev/null; then
  echo "frametop: smoke missing protocol preflight pass" >&2
  errors=1
fi
if grep -F "error in client communication" "$log" >/dev/null; then
  echo "frametop: smoke saw a Wayland client error" >&2
  errors=1
fi
for ((i = 1; i <= count; i++)); do
  if ! grep -E "^${i} ${width}x${height} [1-9][0-9]* " "$log" >/dev/null; then
    echo "frametop: smoke missing a mapped ${width}x${height} commit for screen $i" >&2
    errors=1
  fi
done
exit "$errors"
