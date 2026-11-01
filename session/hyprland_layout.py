#!/usr/bin/env python3
"""Spatial layout for the Hyprland desktop.

The file is ~/.config/frametop/hyprland-layout.json (FT_HYPRLAND_LAYOUT
overrides it). Plasma's ~/.config/frametop-layout.json is never read or
written. Screen identity is the id (hypr-1, hypr-2, ...). The slot is the
Frametop panel number and stays put when another screen is removed.

Aquamarine names monitors WAYLAND-N in creation order. That number is not
the slot. assign_monitors() keeps a session map so a recreated monitor
takes the slot whose previous monitor disappeared, and a monitor that is
still alive keeps its slot even if the list arrives in another order.

Poses from a saved arrangement are relative to the headset heading at the
time they were saved. Restoring them uses the heading now. Nothing here
anchors a panel to a fixed point in the room.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "layout"))
import ft_layout  # noqa: E402

PRIMARY_SIZE = (1920, 1080)
PRIMARY_METRES = 1.5
MAX_SCREENS = 24

LIMITATIONS = ()


def layout_path():
    override = os.environ.get("FT_HYPRLAND_LAYOUT")
    if override:
        return Path(override)
    return Path.home() / ".config" / "frametop" / "hyprland-layout.json"


def _screen(slot, ident=None, size=PRIMARY_SIZE, metres=PRIMARY_METRES):
    return {
        "id": ident or f"hypr-{slot}",
        "slot": slot,
        "size": [int(size[0]), int(size[1])],
        "metres": float(metres),
        "scale": 1.0,
        "curve": 0.0,
    }


def default_layout():
    return {
        "screens": [_screen(1)],
        "primary": "hypr-1",
        "mode": "preset",
        "auto": False,
        "preset": {"kind": "curved", "distance": 2.0, "gap": 0.05, "rows": 1, "height": 0.0},
        "layouts": {},
    }


def load(path=None):
    path = Path(path) if path else layout_path()
    layout = default_layout()
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return layout
    if not isinstance(saved, dict):
        return layout
    screens = []
    for entry in saved.get("screens") or []:
        if not isinstance(entry, dict) or "slot" not in entry or "id" not in entry:
            continue
        slot = int(entry["slot"])
        if slot < 1 or slot > MAX_SCREENS:
            continue
        size = entry.get("size") or list(PRIMARY_SIZE)
        screens.append({
            "id": str(entry["id"]),
            "slot": slot,
            "size": [int(size[0]), int(size[1])],
            "metres": float(entry.get("metres", PRIMARY_METRES)),
            "scale": float(entry.get("scale", 1.0)),
            "curve": float(entry.get("curve", 0.0)),
            **{k: entry[k] for k in ("pos", "face", "roll", "hidden", "pin") if k in entry},
        })
    if screens:
        layout["screens"] = screens
    if saved.get("primary"):
        layout["primary"] = saved["primary"]
    layout["mode"] = saved.get("mode") or "preset"
    layout["auto"] = bool(saved.get("auto", False))
    preset = saved.get("preset")
    if isinstance(preset, dict):
        layout["preset"].update(preset)
    named = saved.get("layouts")
    if isinstance(named, dict):
        layout["layouts"] = named
    if saved.get("active"):
        layout["active"] = saved["active"]
    for key in ("profiles", "visibility", "default_profile", "hosts"):
        if key in saved:
            layout[key] = saved[key]
    return layout


def save(layout, path=None):
    path = Path(path) if path else layout_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(layout, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def screens_by_slot(layout):
    return sorted(layout.get("screens") or [], key=lambda s: int(s["slot"]))


def max_slot(layout):
    screens = screens_by_slot(layout)
    return max((int(s["slot"]) for s in screens), default=1)


def screen_specs(layout):
    """One ft-screens --screen value per slot, including gaps."""
    by_slot = {int(s["slot"]): s for s in layout.get("screens") or []}
    specs = []
    for slot in range(1, max_slot(layout) + 1):
        screen = by_slot.get(slot)
        if not screen:
            specs.append(f"{PRIMARY_SIZE[0]}x{PRIMARY_SIZE[1]}@{PRIMARY_METRES:.3f}")
            continue
        w, h = screen["size"]
        specs.append(f"{int(w)}x{int(h)}@{float(screen['metres']):.3f}")
    return specs


def shell_export(layout=None):
    layout = layout or load()
    specs = screen_specs(layout)
    lines = [
        f"count={max_slot(layout)}",
        f"outputs={len(layout.get('screens') or [])}",
        "screens=" + " ".join(specs),
    ]
    return "\n".join(lines)


def _monitor_number(name):
    digits = ""
    for ch in reversed(str(name)):
        if ch.isdigit():
            digits = ch + digits
        else:
            break
    return int(digits) if digits else 0


def assign_monitors(layout, live_names, previous):
    """Map live Aquamarine names onto stable slots.

    previous is {monitor_name: screen_id}. Monitors that are still listed
    keep that id's slot. A name that disappeared frees its slot. A new name
    takes the lowest freed slot, not the next integer in its own name.
    The order of live_names does not matter.
    """
    previous = dict(previous or {})
    by_id = {s["id"]: s for s in screens_by_slot(layout)}
    live = list(dict.fromkeys(live_names))
    kept = {}
    used_ids = set()
    for name in live:
        ident = previous.get(name)
        screen = by_id.get(ident) if ident else None
        if screen and ident not in used_ids:
            kept[name] = screen
            used_ids.add(ident)
    free = [s for s in screens_by_slot(layout) if s["id"] not in used_ids]
    fresh = [name for name in live if name not in kept]
    fresh.sort(key=_monitor_number)
    claims = []
    released = [name for name in previous if name not in live]
    for name, screen in kept.items():
        claims.append((name, int(screen["slot"]), screen["id"]))
    for name, screen in zip(fresh, free):
        claims.append((name, int(screen["slot"]), screen["id"]))
    claims.sort(key=lambda item: item[1])
    mapping = {name: ident for name, _slot, ident in claims}
    return {"claims": claims, "mapping": mapping, "released": released}


def poses_for(layout):
    """Head-frame poses for the enabled screens, in slot order."""
    enabled = screens_by_slot(layout)
    synthetic_screens = []
    for screen in enabled:
        entry = {
            "size": list(screen["size"]),
            "metres": float(screen["metres"]),
            "scale": float(screen.get("scale", 1.0)),
            "curve": float(screen.get("curve", 0.0)),
        }
        if layout.get("mode") == "custom" and "pos" in screen:
            entry["pos"] = list(screen["pos"])
            entry["face"] = list(screen.get("face") or [0, 0])
            entry["roll"] = float(screen.get("roll", 0))
        synthetic_screens.append(entry)
    synthetic = {
        "mode": "custom" if layout.get("mode") == "custom" and all("pos" in s for s in synthetic_screens) else "preset",
        "preset": dict(layout.get("preset") or default_layout()["preset"]),
        "screens": synthetic_screens,
    }
    original = ft_layout.backend
    ft_layout.backend = lambda: "screens"
    try:
        return ft_layout.plan(synthetic, len(synthetic_screens))
    finally:
        ft_layout.backend = original


def monitor_row(layout):
    """Left to right. Saved poses order the row; otherwise the slot order."""
    screens = screens_by_slot(layout)
    if layout.get("mode") == "custom" and all("pos" in s for s in screens):
        return sorted(screens, key=lambda s: float(s["pos"][0]))
    return screens


def monitor_commands(layout, mapping):
    """Hyprland monitor rules, one row, edges touching, so the pointer can cross."""
    by_id = {ident: name for name, ident in mapping.items()}
    x = 0
    commands = []
    for screen in monitor_row(layout):
        name = by_id.get(screen["id"])
        if not name:
            continue
        w, h = int(screen["size"][0]), int(screen["size"][1])
        scale = float(screen.get("scale", 1.0))
        scale_text = f"{scale:g}"
        lua = (
            "hl.monitor({"
            f'output="{name}", mode="{w}x{h}@60", position="{x}x0", scale={scale_text}'
            "})"
        )
        commands.append({"monitor": name, "slot": int(screen["slot"]), "x": x, "eval": lua})
        x += w
    return commands


def place_commands(layout, eye, heading):
    """World-space place commands. eye is (x, y, z), heading is degrees."""
    enabled = screens_by_slot(layout)
    poses = poses_for(layout)
    commands = []
    for screen, pose in zip(enabled, poses):
        world = ft_layout.turn_yaw(pose["pos"], heading)
        center = tuple(e + v for e, v in zip(eye, world))
        slot = int(screen["slot"])
        commands.append({
            "slot": slot,
            "id": screen["id"],
            "width": f"width {slot} {float(screen['metres']):.4f}",
            "curve": f"curve {slot} {float(screen.get('curve', 0)):.3f}",
            "place": "place %d %.4f %.4f %.4f %.3f %.3f %.3f" % (
                slot, *center, pose["face"][0] + heading, pose["face"][1], pose["roll"]),
            "size": "slot %d %d %d %.3f" % (
                slot, int(screen["size"][0]), int(screen["size"][1]), float(screen["metres"])),
        })
    return commands


def sync_actions(layout, live_names, previous, placed_ids, baseline=0):
    """What a poll should do. place only for a screen that was not placed yet.

    A panel the user has already placed is listed in placed_ids, so a later
    poll does not move it. That is what keeps a panel the user dragged in VR
    where they left it. `baseline` is how many monitors startup already
    asked Hyprland to create; the poll does not create those again.
    """
    live = list(dict.fromkeys(live_names))
    assigned = assign_monitors(layout, live, previous)
    mapping = assigned["mapping"]
    claimed = {name for name, _slot, _ident in assigned["claims"]}
    new_ids = [ident for _name, _slot, ident in assigned["claims"] if ident not in set(placed_ids)]
    floor = max(len(live), int(baseline or 0))
    return {
        "claims": [(name, slot) for name, slot, _ident in assigned["claims"]],
        "released": list(assigned["released"]),
        "mapping": mapping,
        "monitors": monitor_commands(layout, mapping),
        "place_ids": new_ids,
        "create": max(0, len(screens_by_slot(layout)) - floor),
        "remove": [name for name in live if name not in claimed],
    }


def set_count(layout, n):
    """Grow or shrink the layout to n screens. The last screen stays."""
    n = max(1, min(MAX_SCREENS, int(n)))
    while len(screens_by_slot(layout)) < n:
        add_screen(layout)
    while len(screens_by_slot(layout)) > n:
        remove_screen(layout, int(screens_by_slot(layout)[-1]["slot"]))
    return layout


def add_screen(layout, size=PRIMARY_SIZE, metres=PRIMARY_METRES):
    screens = screens_by_slot(layout)
    if len(screens) >= MAX_SCREENS:
        raise RuntimeError(f"frametop: at most {MAX_SCREENS} Hyprland screens")
    used_slots = {int(s["slot"]) for s in screens}
    slot = next(i for i in range(1, MAX_SCREENS + 1) if i not in used_slots)
    numbers = []
    for screen in screens:
        tail = screen["id"].rsplit("-", 1)[-1]
        if tail.isdigit():
            numbers.append(int(tail))
    ident = f"hypr-{max(numbers, default=0) + 1}"
    screens.append(_screen(slot, ident, size, metres))
    layout["screens"] = screens
    return layout


def remove_screen(layout, slot):
    screens = screens_by_slot(layout)
    if len(screens) <= 1:
        raise RuntimeError("frametop: the last Hyprland screen stays")
    slot = int(slot)
    kept = [s for s in screens if int(s["slot"]) != slot]
    if len(kept) == len(screens):
        raise RuntimeError(f"frametop: no Hyprland screen {slot}")
    removed = next(s for s in screens if int(s["slot"]) == slot)
    layout["screens"] = kept
    if layout.get("primary") == removed["id"]:
        layout["primary"] = kept[0]["id"]
    return removed


def screen_by_index(layout, index):
    """index is the 0-based slot, which is what Display Settings sends."""
    slot = int(index) + 1
    for screen in layout.get("screens") or []:
        if int(screen["slot"]) == slot:
            return screen
    raise RuntimeError(f"frametop: no Hyprland screen {slot}")


def capture_windows(clients, monitors):
    """Open Hyprland windows, as a profile stores them.

    `clients` and `monitors` are hyprctl's JSON. The shell and Steam's own
    windows are left out. A window's screen is the monitor it is on now.
    """
    names = {}
    for monitor in monitors or []:
        if isinstance(monitor, dict) and monitor.get("name"):
            names[int(monitor.get("id", -1))] = monitor["name"]
    skip = {"quickshell", "steam", "steamwebhelper"}
    windows = []
    for client in clients or []:
        if not isinstance(client, dict):
            continue
        app = str(client.get("class") or client.get("initialClass") or "")
        if not app or app.lower() in skip:
            continue
        workspace = client.get("workspace") or {}
        at = client.get("at") or [0, 0]
        size = client.get("size") or [0, 0]
        windows.append({
            "app": app,
            "title": str(client.get("title") or ""),
            "monitor": names.get(int(client.get("monitor", -1)), ""),
            "workspace": int(workspace.get("id") or 1),
            "floating": bool(client.get("floating")),
            "at": [int(at[0]), int(at[1])],
            "size": [int(size[0]), int(size[1])],
            "cmd": [str(part) for part in (client.get("cmd") or []) if part],
        })
    return windows


def save_profile(layout, name, clients, monitors, mapping):
    """Save the arrangement and the windows that are open on it."""
    name = save_named(layout, name)
    by_name = {str(monitor): str(ident) for monitor, ident in (mapping or {}).items()}
    slot_for = {screen["id"]: int(screen["slot"]) for screen in screens_by_slot(layout)}
    windows = capture_windows(clients, monitors)
    for window in windows:
        ident = by_name.get(window["monitor"], "")
        window["screen"] = slot_for.get(ident, 1)
    hidden = [int(screen["slot"]) for screen in screens_by_slot(layout) if screen.get("hidden")]
    layout.setdefault("profiles", {})[name] = {"windows": windows, "hidden": hidden}
    return name


def profile_record(layout, name):
    return (layout.get("profiles") or {}).get(name) or {}


def profile_window_rows(layout, name):
    """The rows Display Settings lists: app, and where it opens."""
    rows = []
    for window in profile_record(layout, name).get("windows") or []:
        where = f"screen {int(window.get('screen') or 1)}"
        if window.get("workspace"):
            where += f", workspace {int(window['workspace'])}"
        if window.get("floating"):
            where += ", floating"
        rows.append({"app": window.get("app") or "?", "where": where})
    return rows


def remove_profile_window(layout, name, index):
    windows = profile_record(layout, name).get("windows") or []
    if 0 <= int(index) < len(windows):
        windows.pop(int(index))


def command_for_pid(pid):
    """The process command line, for reopening a window that is not open."""
    try:
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes().split(b"\0")
    except (OSError, ValueError):
        return []
    return [part.decode(errors="replace") for part in raw if part]


def open_profile_evals(layout, name, mapping, live_clients=None):
    """Lua for hyprctl eval that puts each saved window on its screen.

    An open window of the same class is moved. Otherwise the saved command
    is started on that screen's workspace.
    """
    by_id = {str(ident): str(monitor) for monitor, ident in (mapping or {}).items()}
    slot_id = {int(screen["slot"]): screen["id"] for screen in screens_by_slot(layout)}
    waiting = {}
    for client in live_clients or []:
        if not isinstance(client, dict):
            continue
        app = str(client.get("class") or client.get("initialClass") or "").lower()
        address = str(client.get("address") or "")
        if app and address:
            waiting.setdefault(app, []).append(address)
    evals = []
    for window in profile_record(layout, name).get("windows") or []:
        ident = slot_id.get(int(window.get("screen") or 1), "")
        monitor = by_id.get(ident, "")
        workspace = int(window.get("workspace") or 1)
        app = str(window.get("app") or "").lower()
        addresses = waiting.get(app) or []
        address = addresses.pop(0) if addresses else ""
        focus = ""
        if monitor:
            focus = f'hl.dispatch(hl.dsp.focus({{ monitor = "{monitor}" }})); '
        focus += f"hl.dispatch(hl.dsp.focus({{ workspace = {workspace} }})); "
        if address:
            evals.append(
                focus
                + f'hl.dispatch(hl.dsp.focus({{ window = "{address}" }})); '
                + f"hl.dispatch(hl.dsp.window.move({{ workspace = {workspace}, follow = false }}))"
            )
        else:
            cmd = " ".join(window.get("cmd") or [])
            if cmd:
                evals.append(focus + f"hl.dispatch(hl.dsp.exec_cmd({json.dumps(cmd)}))")
    return evals


def save_named(layout, name):
    name = " ".join(name.split())
    if not name:
        raise RuntimeError("frametop: the layout needs a name")
    snapshot = []
    for screen in screens_by_slot(layout):
        snapshot.append({k: screen[k] for k in screen if k in (
            "id", "slot", "size", "metres", "scale", "curve", "pos", "face", "roll", "hidden", "pin")})
    layout.setdefault("layouts", {})[name] = {"screens": snapshot, "primary": layout.get("primary")}
    layout["active"] = name
    return name


def use_named(layout, name):
    named = (layout.get("layouts") or {}).get(name)
    if not named:
        raise RuntimeError(f"frametop: no Hyprland layout called {name!r}")
    by_id = {s["id"]: s for s in screens_by_slot(layout)}
    for saved in named.get("screens") or []:
        screen = by_id.get(saved.get("id"))
        if not screen:
            continue
        for key in ("size", "metres", "scale", "curve", "pos", "face", "roll", "hidden", "pin"):
            if key in saved:
                screen[key] = saved[key]
        if "hidden" not in saved:
            screen.pop("hidden", None)
        if "pin" not in saved:
            screen.pop("pin", None)
    if named.get("primary"):
        layout["primary"] = named["primary"]
    layout["mode"] = "custom"
    layout["active"] = name


def control_name():
    """Abstract control socket for this Hyprland desktop, without the leading NUL."""
    return os.environ.get("FT_HYPRLAND_CONTROL") or os.environ.get("FT_HYPR_CONTROL") or "ft_hyprland"


def socket_name():
    """ft-screens Wayland socket for this Hyprland desktop."""
    return os.environ.get("FT_HYPRLAND_SOCKET") or "ft-hyprland-0"


def active():
    """True when Display Settings should edit this layout instead of Plasma's.

    The shell's private runtime is not where ft-screens puts its socket, so
    the host runtime is checked as well.
    """
    forced = os.environ.get("FT_DISPLAY_COMPOSITOR", "")
    if forced == "hyprland":
        return True
    if forced == "plasma":
        return False
    name = socket_name()
    runtimes = []
    private = os.environ.get("XDG_RUNTIME_DIR")
    if private:
        runtimes.append(private)
    host = f"/run/user/{os.getuid()}"
    if host not in runtimes:
        runtimes.append(host)
    return any(os.path.exists(os.path.join(runtime, name)) for runtime in runtimes)


def visibility_commands(layout):
    """The same visibility and hidden-screen commands Plasma sends at start."""
    v = ft_layout.visibility(layout)
    commands = [
        f"visibility {v['mode']}",
        f"wrist {float(v['wrist_angle']):.1f}",
        f"gesture {v['gesture_hand']} {float(v['gesture_angle']):.1f}",
        f"controllers {v['controllers']}",
        f"ingames {v['in_games']}",
    ]
    for screen in screens_by_slot(layout):
        word = "conceal" if screen.get("hidden") else "reveal"
        commands.append(f"{word} {int(screen['slot'])}")
    return commands


def arrange_commands(layout, eye, heading):
    """place/width/curve for Arrange now and Reset Screen Layout."""
    commands = []
    for item in place_commands(layout, eye, heading):
        commands.extend([item["width"], item["curve"], item["place"]])
    return commands


def parse_head(reply):
    parts = (reply or "").split()
    if len(parts) < 5 or parts[0] != "ok":
        raise RuntimeError("no headset pose yet")
    return tuple(map(float, parts[1:4])), float(parts[4])


def use_hidden(layout, name):
    """A profile's hidden screens as each screen's own setting."""
    hidden = {int(n) for n in (profile_record(layout, name).get("hidden") or [])}
    for screen in screens_by_slot(layout):
        if int(screen["slot"]) in hidden:
            screen["hidden"] = True
        else:
            screen.pop("hidden", None)


def write_launchers(layout):
    """SteamVR launch-bar entries that open Hyprland profiles, not Plasma's ft-layout."""
    apps = Path.home() / ".local" / "share" / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve().parent / "hyprland_profile.py"
    want = {}
    for name in sorted((layout.get("layouts") or {}).keys()):
        safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-") or "profile"
        quoted = '"' + name.replace('"', '\\"') + '"'
        want[f"frametop-profile-{safe}.desktop"] = "\n".join([
            "[Desktop Entry]",
            "Type=Application",
            f"Name=Frametop: {name}",
            "Comment=Open the Frametop desktop in this profile: its screens and apps",
            f"Exec=python3 {script} open {quoted}",
            "Icon=preferences-desktop-display",
            "Categories=Utility;",
            "X-Frametop-Profile=true",
            "",
        ])
    for path in apps.glob("frametop-profile-*.desktop"):
        if path.name not in want:
            path.unlink()
    for name, text in want.items():
        dest = apps / name
        if dest.exists() and dest.read_text(encoding="utf-8") == text:
            continue
        dest.write_text(text, encoding="utf-8")


def ask_screens(text):
    return ft_layout.screens_socket().ask(text)


def apply_live(layout, ask):
    """Place every Hyprland screen from the current heading, then visibility and remotes."""
    eye, heading = parse_head(ask("head"))
    for command in arrange_commands(layout, eye, heading):
        ask(command)
    for command in visibility_commands(layout):
        ask(command)
    if layout.get("hosts"):
        sock = ft_layout.screens_socket()
        ft_layout.start_remotes(sock, layout)
        ft_layout.place_remotes(sock, layout, max_slot(layout), eye, heading)
    return 0


def apply_profile(name, ask=None):
    """Open a named layout (or the current one) the way Plasma's ft-layout use does."""
    data = load()
    if name:
        use_named(data, name)
        use_hidden(data, name)
        ft_layout.open_remotes(data, name)
        save(data)
    ask = ask or ask_screens
    apply_live(data, ask)
    return data


def start_name(layout):
    name = os.environ.get("FT_PROFILE") or layout.get("default_profile")
    return name if name and name in (layout.get("layouts") or {}) else None


def cli_reset(ask=None):
    """Put the Hyprland screens back in the saved layout. Same job as ft-layout reset."""
    data = load()
    name = data.get("active") if data.get("mode") == "custom" else None
    if name and name not in (data.get("layouts") or {}):
        name = None
    apply_profile(name or "", ask=ask)
    return 0


def cli_capture(ask=None):
    ask = ask or ask_screens
    data = load()
    eye, heading = parse_head(ask("head"))
    for screen in screens_by_slot(data):
        got = ask(f"get {int(screen['slot'])}")
        pose = ft_layout.parse_get(got)
        screen.update(ft_layout.relative_pose(pose["center"], pose["x"], pose["z"], eye, heading))
        screen["metres"] = round(float(pose["metres"]), 3)
        screen["curve"] = round(float(pose["curve"]), 3)
        screen.pop("pin", None)
        if "rel" in pose:
            screen["pin"] = {"hand": pose["hand"], "rel": pose["rel"]}
    data["mode"] = "custom"
    data.pop("active", None)
    if data.get("hosts"):
        ft_layout.capture_remotes(ft_layout.screens_socket(), data, eye, heading)
    save(data)
    return 0


def set_hidden(which, hidden):
    data = load()
    slots = [int(s["slot"]) for s in screens_by_slot(data)]
    remotes = {num: d for num, _, d in ft_layout.remote_displays(data)}
    if which == "all":
        picked, picked_remote = list(slots), list(remotes)
    elif which.isdigit() and int(which) in remotes:
        picked, picked_remote = [], [int(which)]
    elif which.isdigit() and int(which) in slots:
        picked, picked_remote = [int(which)], []
    else:
        raise RuntimeError(f"no screen {which} (1 to {max(slots, default=0)}, or a remote display's number)")
    by_slot = {int(s["slot"]): s for s in data.get("screens") or []}
    for slot in picked:
        if hidden:
            by_slot[slot]["hidden"] = True
        else:
            by_slot[slot].pop("hidden", None)
    for num in picked_remote:
        if hidden:
            remotes[num]["hidden"] = True
        else:
            remotes[num].pop("hidden", None)
    save(data)
    sock = ft_layout.screens_socket()
    for num in picked + picked_remote:
        sock.ask(f"{'conceal' if hidden else 'reveal'} {num}")


def open_windows(name):
    """Hyprland windows for a profile. Isolated so tests can skip hyprctl."""
    import hyprland_profile
    hyprland_profile.open_windows(name)


LAYOUT_COMMANDS = (
    "apply", "reset", "capture", "save", "use", "start", "open", "default",
    "layouts", "rename", "delete", "launchers", "plan", "scale", "screen-args",
    "remote-view", "toggle", "hide", "show", "hidden", "pin", "unpin", "remote",
)


def cli(argv, ask=None):
    """ft-layout commands against the Hyprland layout and compositor.

    Returns an exit code, or None if the command is not one of these.
    """
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd not in LAYOUT_COMMANDS:
        return None
    ask = ask or ask_screens
    data = load()
    if cmd == "toggle":
        print(ask("toggle"))
        return 0
    if cmd in ("hide", "show") and len(argv) == 3:
        set_hidden(argv[2], cmd == "hide")
        return 0
    if cmd == "hidden":
        print(" ".join(str(int(s["slot"])) for s in screens_by_slot(data) if s.get("hidden")))
        return 0
    if cmd in ("pin", "unpin") and len(argv) >= 3:
        print(ask(" ".join(argv[1:])))
        return 0
    if cmd == "reset":
        return cli_reset(ask=ask)
    if cmd == "apply":
        wait = float(argv[argv.index("--wait") + 1]) if "--wait" in argv else 0
        if wait and not data.get("auto", True):
            for command in visibility_commands(data):
                ask(command)
            return 0
        name = data.get("active") if data.get("mode") == "custom" else None
        apply_profile(name if name in (data.get("layouts") or {}) else "", ask=ask)
        return 0
    if cmd == "capture":
        return cli_capture(ask=ask)
    if cmd == "save" and len(argv) == 3:
        ft_layout.check_name(argv[2])
        cli_capture(ask=ask)
        data = load()
        try:
            import hyprland_profile
            env, runtime = hyprland_profile.hypr_env()
            save_profile(data, argv[2], hyprland_profile.hypr_json("clients", env),
                         hyprland_profile.hypr_json("monitors", env), hyprland_profile.output_map(runtime))
        except (OSError, RuntimeError, ValueError):
            save_named(data, argv[2])
        save(data)
        write_launchers(data)
        return 0
    if cmd == "use" and len(argv) == 3:
        apply_profile(argv[2], ask=ask)
        open_windows(argv[2])
        return 0
    if cmd == "open" and len(argv) == 3:
        if argv[2] not in (data.get("layouts") or {}):
            raise RuntimeError(f"no profile called {argv[2]!r}")
        apply_profile(argv[2], ask=ask)
        open_windows(argv[2])
        return 0
    if cmd == "start":
        name = start_name(data)
        apply_profile(name or "", ask=ask)
        if name:
            open_windows(name)
        return 0
    if cmd == "layouts":
        for name in sorted((data.get("layouts") or {}).keys()):
            print(("* " if name == data.get("active") and data.get("mode") == "custom" else "  ") + name)
        return 0
    if cmd == "rename" and len(argv) == 4:
        named = data.setdefault("layouts", {})
        if argv[2] not in named:
            raise RuntimeError(f"no layout called {argv[2]!r}")
        named[argv[3]] = named.pop(argv[2])
        profiles = data.get("profiles") or {}
        if argv[2] in profiles:
            profiles[argv[3]] = profiles.pop(argv[2])
        if data.get("default_profile") == argv[2]:
            data["default_profile"] = argv[3]
        if data.get("active") == argv[2]:
            data["active"] = argv[3]
        save(data)
        write_launchers(data)
        return 0
    if cmd == "delete" and len(argv) == 3:
        if (data.get("layouts") or {}).pop(argv[2], None) is None:
            raise RuntimeError(f"no layout called {argv[2]!r}")
        (data.get("profiles") or {}).pop(argv[2], None)
        if data.get("default_profile") == argv[2]:
            data.pop("default_profile", None)
        if data.get("active") == argv[2]:
            data.pop("active", None)
        save(data)
        write_launchers(data)
        return 0
    if cmd == "launchers":
        write_launchers(data)
        return 0
    if cmd == "default" and len(argv) == 3:
        if argv[2] == "none":
            data.pop("default_profile", None)
        elif argv[2] in (data.get("layouts") or {}):
            data["default_profile"] = argv[2]
        else:
            raise RuntimeError(f"no profile called {argv[2]!r}")
        save(data)
        return 0
    if cmd == "plan":
        print(json.dumps(poses_for(data)))
        return 0
    if cmd == "screen-args":
        print(" ".join(
            f"--screen {int(s['size'][0])}x{int(s['size'][1])}@{float(s['metres']):.3f}"
            for s in screens_by_slot(data)))
        return 0
    if cmd == "scale":
        return 0
    if cmd == "remote-view":
        print("0 0 0 0 0 0")
        return 0
    if cmd == "remote":
        original_load, original_save = ft_layout.load_layout, ft_layout.save_layout
        ft_layout.load_layout = load
        ft_layout.save_layout = save
        try:
            ft_layout.remote_command(argv[2:])
        finally:
            ft_layout.load_layout = original_load
            ft_layout.save_layout = original_save
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    layout = load()
    if cmd == "shell-export":
        print(shell_export(layout))
        return 0
    if cmd == "status":
        print(shell_export(layout))
        print("primary=" + str(layout.get("primary")))
        print("path=" + str(layout_path()))
        return 0
    if cmd == "add":
        add_screen(layout)
        save(layout)
        print(shell_export(layout))
        return 0
    if cmd == "remove" and len(argv) == 3:
        remove_screen(layout, int(argv[2]))
        save(layout)
        print(shell_export(layout))
        return 0
    if cmd == "limitations":
        for line in LIMITATIONS:
            print(line)
        return 0
    print("usage: hyprland_layout.py shell-export|status|add|remove SLOT|limitations", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
