#!/usr/bin/env python3
"""Keep Hyprland monitors matched to Frametop slots.

Runs inside the nested Hyprland process. A missing hyprctl or a refused
command is logged and the compositor stays up. This process does not stop
Hyprland, Quickshell, or any other desktop.
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import hyprland_layout as layout


def map_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "frametop-output-map.json"


def load_state():
    try:
        data = json.loads(map_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {
        "mapping": data.get("mapping") or {},
        "placed": list(data.get("placed") or []),
        "rules": data.get("rules") or {},
    }


def save_state(state):
    path = map_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"frametop: output map not saved: {exc}", file=sys.stderr)


def hyprctl(args, runner=None):
    if runner:
        return runner(args)
    proc = subprocess.run(["hyprctl", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "hyprctl failed").strip())
    return proc.stdout


def monitors_from_json(text):
    data = json.loads(text)
    names = []
    for entry in data:
        name = entry.get("name")
        if name:
            names.append(name)
    return names


def step(live_names, state, screens, baseline):
    """One poll. Returns the commands a caller can apply, and the next state.

    `screens` is a layout dict. State keeps the session map and which ids
    have already been placed, so a later poll does not move those panels.
    """
    actions = layout.sync_actions(screens, live_names, state.get("mapping") or {}, state.get("placed") or [], baseline)
    commands = []
    for name in actions["remove"]:
        commands.append(("remove", name))
    for _ in range(actions["create"]):
        commands.append(("create", "wayland"))
    by_slot = {int(screen["slot"]): screen for screen in layout.screens_by_slot(screens)}
    for name, slot in actions["claims"]:
        screen = by_slot.get(int(slot))
        if screen and (state.get("mapping") or {}).get(name) != screen["id"]:
            width, height = int(screen["size"][0]), int(screen["size"][1])
            metres = float(screen["metres"])
            # A claim past the launch count is refused until the slot exists.
            commands.append(("slot", f"slot {int(slot)} {width} {height} {metres:.3f}"))
        commands.append(("claim", f"claim {name} {slot}"))
    for rule in actions["monitors"]:
        if state.get("rules", {}).get(rule["monitor"]) == rule["eval"]:
            continue
        commands.append(("monitor", rule["eval"]))
    place_ids = []
    if actions["place_ids"]:
        # Poses are filled in by the caller when a head pose exists. The ids
        # are recorded only after the caller places them.
        place_ids = list(actions["place_ids"])
    next_state = {
        "mapping": {name: screens_id for name, screens_id in actions["mapping"].items()},
        "placed": list(state.get("placed") or []),
        "rules": dict(state.get("rules") or {}),
    }
    for rule in actions["monitors"]:
        if any(cmd[0] == "monitor" and cmd[1] == rule["eval"] for cmd in commands):
            next_state["rules"][rule["monitor"]] = rule["eval"]
    return {
        "commands": commands,
        "place_ids": place_ids,
        "state": next_state,
        "actions": actions,
        "create": actions["create"],
        "remove": actions["remove"],
    }


def note_placed(state, ids):
    placed = list(state.get("placed") or [])
    for ident in ids:
        if ident not in placed:
            placed.append(ident)
    state["placed"] = placed
    return state


def send_control(text, name=None):
    """One datagram to ft-screens. False when the compositor is not up yet."""
    name = name or os.environ.get("FT_HYPR_CONTROL") or "ft_hyprland"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.settimeout(0.5)
    try:
        sock.bind("")
        sock.sendto(text.encode(), b"\0" + name.encode())
        return True
    except OSError:
        return False
    finally:
        sock.close()


def settle_baseline(baseline, live_count, enabled, short):
    """Trust startup's output count, then take over if those outputs never appear.

    The first polls do not create monitors the startup script already asked
    for. If the live count stays below that for a few polls, the create did
    not land and the poll creates the missing ones.
    """
    if live_count >= baseline:
        return max(baseline, enabled), 0
    short += 1
    if short >= 3:
        return live_count, 0
    return baseline, short


def monitor_for_slot(mapping, slot, screens=None):
    """The live output whose stable id is hypr-<slot>."""
    try:
        number = int(slot)
        want = next((s["id"] for s in layout.screens_by_slot(screens)
                     if int(s["slot"]) == number), "") if screens is not None else f"hypr-{number}"
    except (TypeError, ValueError):
        return ""
    for name, ident in (mapping or {}).items():
        if ident == want and name:
            return name
    return ""


def pointer_focus_eval(mapping, slot, current, screens=None):
    """Lua that focuses the panel under the laser. Empty when nothing changed."""
    if not slot:
        return "", current or ""
    name = monitor_for_slot(mapping, slot, screens)
    if not name or name == current:
        return "", current or ""
    return f'hl.dispatch(hl.dsp.focus({{ monitor = "{name}" }}))', name


def read_pointer_slot():
    runtime = os.environ.get("FT_HOST_RUNTIME") or ""
    control = os.environ.get("FT_HYPR_CONTROL") or os.environ.get("FT_HYPRLAND_CONTROL") or ""
    if not runtime or not control or not control.replace("_", "").replace("-", "").isalnum():
        return 0
    path = Path(runtime) / f"frametop-pointer-{control}"
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def apply_commands(commands):
    """Apply a poll in order; a failed control send retries on the next poll."""
    for kind, arg in commands:
        if kind == "create":
            hyprctl(["output", "create", "wayland"])
        elif kind == "remove":
            hyprctl(["output", "remove", arg])
        elif kind == "monitor":
            hyprctl(["eval", arg])
        elif kind in ("slot", "claim"):
            if not send_control(arg):
                raise RuntimeError(f"ft-screens did not receive {kind}")


def main():
    baseline = int(os.environ.get("FT_HYPR_OUTPUTS") or os.environ.get("FT_SCREEN_COUNT") or "1")
    short = 0
    state = load_state()
    focused = ""
    tick = 0
    visibility_sent = False
    screens = layout.load()
    while True:
        try:
            expr, nxt = pointer_focus_eval(state.get("mapping") or {}, read_pointer_slot(), focused, screens)
            if expr:
                hyprctl(["eval", expr])
            focused = nxt
            if tick % 5 != 0:
                tick += 1
                time.sleep(0.2)
                continue
            tick += 1
            raw = hyprctl(["monitors", "-j"])
            live = monitors_from_json(raw)
            screens = layout.load()
            result = step(live, state, screens, baseline)
            apply_commands(result["commands"])
            # New screens get their first pose from ft-screens (a row in front
            # of the headset). This loop does not send place: a poll must not
            # pull a panel back after the user moves it. Arrange does that.
            state = result["state"]
            state["placed"] = list(dict.fromkeys([*(state.get("placed") or []), *result["place_ids"]]))
            save_state(state)
            if not visibility_sent and live:
                for command in layout.visibility_commands(screens):
                    send_control(command)
                visibility_sent = True
            baseline, short = settle_baseline(
                baseline, len(live), len(screens.get("screens") or []), short)
        except Exception as exc:
            print(f"frametop: output sync: {exc}", file=sys.stderr)
        time.sleep(0.2)


if __name__ == "__main__":
    main()
