"""Monitor alignment: puts each remote display's panel on the physical monitor it streams.

ft-layout align runs it, on the Frame host (docs/monitor-alignment.md):
each display's stream switches to the host's FrametopAlign app, which shows markers on the real monitor,
align/build/ft-align finds them and moves the panels live, and a display goes back to its stream when it's
locked. A session is one run of this; positions aren't saved, because SteamVR's room coordinates can move
between sessions. Sizes are: a monitor measured once needs no measuring again.

Stand-alone geometry (join) needs nothing but the standard library, so tests can run it anywhere.
"""
import json
import math
import os
import re
import signal
import socket
import subprocess
import threading
import time
import uuid

import ft_layout

SOCKET = "\0ft_align"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMD = os.environ.get("FT_CAMD") or os.path.join(ROOT, "hands", "build", "ft-camd")   # FT_CAMD: a copy that has its capabilities
FT_ALIGN = os.path.join(ROOT, "align", "build", "ft-align")
IN_BOX = os.path.join(ROOT, "scripts", "in-box")
APP = "FrametopAlign"
TAGS_PER_DISPLAY = 4
GUESS_WIDTH_M = 0.6          # a monitor that hasn't been measured: the fit finds the real size
MEASURED_BELOW_MM = 10       # a size is worth keeping when the fit is at least this good...
MEASURED_FROM_SPOTS = 12     # ...from this many places (a still head can't tell size from distance)
READY_BELOW_MM = 5           # the figure that says "good"
TIME_LIMIT_S = 300
HOLD_S = 3                   # a display locks itself after staying good this long
MEASURING_SPOTS = 30         # a first run also needs this many places before it locks: the size settles last
WIDTH_STEADY_M = 0.002       # ...and its width has to stay within this over the hold
LIVE_WAIT_S = 30


def join_panels(left, right, width, radius=0):
    """Two equal panels as arcs of one cylinder, tangent at the seam: (left pose, right pose, radius, turn in
    degrees, depth of the curve in metres). Poses are 12 numbers, row by row. radius 0 keeps the turn the
    panels already have between them, so they go on facing as the real monitors do."""
    col = lambda m, c: [m[c], m[4 + c], m[8 + c]]
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    add = lambda a, b, s=1.0: [x + s * y for x, y in zip(a, b)]
    unit = lambda a: [x / math.sqrt(dot(a, a)) for x in a]
    cross = lambda a, b: [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    up = unit(add(col(left, 1), col(right, 1)))
    flat = lambda v: unit(add(v, up, -dot(v, up)))
    nl, nr = flat(col(left, 2)), flat(col(right, 2))
    measured = math.acos(max(-1.0, min(1.0, dot(nl, nr))))
    if radius <= 0:
        if measured < 1e-3:
            raise ValueError("these panels are parallel, so give a radius")
        radius = width / measured
    phi = width / radius
    n = unit(add(nl, nr))
    t = cross(up, n)
    lp, rp = col(left, 3), col(right, 3)
    if dot(t, add(rp, lp, -1)) <= 0:
        raise ValueError("these panels are the wrong way round, or facing away from each other")
    seam = [(a + b) / 2 for a, b in zip(add(lp, col(left, 0), width / 2), add(rp, col(right, 0), -width / 2))]
    sag = radius * (1 - math.cos(phi / 2))
    centre = add(seam, n, sag * 2 / 3 + radius)   # on the flat monitors' plane, on average

    def place(sign):
        a = sign * phi / 2
        z = add([x * math.cos(a) for x in n], t, -math.sin(a))
        x = cross(up, z)
        p = add(centre, z, -radius)
        return [v for i in range(3) for v in (x[i], up[i], z[i], p[i])]

    return place(-1), place(1), radius, math.degrees(phi), sag


def first_tag(display, index):
    """A display's first tag ID. A Mac's Sunshine instance N (port 47989 + 100 N) shows 4N to 4N+3."""
    port = display.get("port")
    n = (int(port) - ft_layout.GAMESTREAM_PORT) // 100 if port else index
    return n * TAGS_PER_DISPLAY


def windows_first_tag(display_name):
    """On Windows, \\\\.\\DISPLAYn shows 4(n-1) to 4(n-1)+3 (host/windows/align-markers.ps1)."""
    found = re.search(r"DISPLAY(\d+)$", display_name)
    if not found:
        raise RuntimeError(f"can't tell which monitor {display_name} is")
    return (int(found[1]) - 1) * TAGS_PER_DISPLAY


def windows_tags(displays, monitors):
    """Each Windows display's first tag ID, from Vibepollo's list of the PC's active monitors."""
    names = {m["device_id"]: m.get("display_name", "") for m in monitors}
    out = {}
    for number, display in displays:
        device = display["app"].partition(":")[2]
        if device not in names:
            raise RuntimeError(f"{display.get('label') or display['id']} isn't active on this computer: "
                               "check that the monitor is on and showing it")
        out[number] = windows_first_tag(names[device])
    return out


def spec_entry(number, display, first_id):
    w, h = display.get("size", [2560, 1440])
    known = display.get("physical")
    width = known["width_m"] if known else GUESS_WIDTH_M
    height = known["height_m"] if known else GUESS_WIDTH_M * h / w
    return {"panel": number, "first_id": first_id, "width_m": width, "height_m": height, "measure": not known}


def hint(fit):
    """What would help this display most: the same advice for every head."""
    if "shown_mm" not in fit:
        return "Look toward this display"
    if fit["shown_mm"] < READY_BELOW_MM:
        return "Good: it locks by itself in a moment"
    x, y, _ = fit.get("range_mm", [0, 0, 0])
    if fit.get("distance_m", 0) > 0.95:
        return "Lean closer"
    if y < 150:
        return "Move up and down"
    if x < 200:
        return "Move side to side"
    return "Keep moving slowly"


class AutoLock:
    """Says when a display has been good for long enough. The figure can dip for a moment as frames arrive, so it
    has to stay down; a monitor being measured also needs its size to have settled, since that's kept for good."""

    def __init__(self, measuring):
        self.measuring = measuring
        self.since = None
        self.width = None

    def update(self, fit, now):
        good = fit.get("shown_mm", 1e9) < READY_BELOW_MM and fit.get("spots", 0) >= MEASURED_FROM_SPOTS
        if self.measuring:
            good = good and fit.get("spots", 0) >= MEASURING_SPOTS
            if good and self.width is not None and abs(fit.get("width_m", 0) - self.width) > WIDTH_STEADY_M:
                good = False
        if not good:
            self.since = self.width = None
            return False
        if self.since is None:
            self.since, self.width = now, fit.get("width_m")
        return now - self.since >= HOLD_S


class Session:
    """One alignment, from switching the streams over to putting them back."""

    def __init__(self, host, displays):
        self.host, self.displays = host, displays    # displays: [(panel number, display)]
        self.sock = ft_layout.screens_socket()
        self.mu = threading.Lock()
        self.state, self.message = "starting", ""
        self.fits = {n: {} for n, _ in displays}
        self.locked, self.restored = set(), set()
        self.camd = self.align = None
        self.finish = threading.Event()
        # Windows: one server carries every display and one app shows every monitor's markers, so one panel
        # starts it, and the others stay live until it ends. A Mac's displays each have their own server and app.
        self.shared = any(d["app"].startswith("display:") for _, d in displays)

    # ------------------------------------------------------------ the host

    def cancel(self, display):
        """Quits the app running on this display's server. Sunshine runs one at a time, and nothing else quits it."""
        target = ft_layout.display_target(self.host, display)
        address, _, port = target.partition(":")
        https = int(port or ft_layout.GAMESTREAM_PORT) - 5
        keys = os.path.expanduser("~/.local/share/frametop-stream/" + display["client"])
        with open(os.path.join(keys, "uniqueid.dat")) as f:
            uid = f.read().strip()
        subprocess.run(["curl", "-sk", "-m", "8", "--cert", keys + "/client.pem", "--key", keys + "/key.pem",
                        f"https://{address}:{https}/cancel?uniqueid={uid}&uuid={uuid.uuid4()}"], capture_output=True, check=False)

    def start_stream(self, number, display, app):
        w, h = ft_layout.stream_size(*display.get("size", [2560, 1440]))
        label = f"{self.host.get('name') or self.host['address']}: {display.get('label') or display['id']}"
        self.sock.ask(f"remote {number} start {display['client']} {ft_layout.display_target(self.host, display)} {app} "
                      f"{int(w)}x{int(h)} {int(display.get('fps', 60))} {int(display.get('bitrate', 0))} "
                      f"{ft_layout.remote_size(display)[0]:.4f} {label}")

    def wait_live(self, number):
        end = time.time() + LIVE_WAIT_S
        while time.time() < end:
            if (ft_layout.remotes_running(self.sock) or {}).get(number, "").startswith("live"):
                return True
            time.sleep(0.3)
        return False

    def switch(self, number, display, app):
        self.sock.ask(f"remote {number} stop")
        self.cancel(display)
        self.start_stream(number, display, app)
        return self.wait_live(number)

    # ------------------------------------------------------------ running it

    def fail(self, message):
        with self.mu:
            self.state, self.message = "failed", message
        ft_layout.log("alignment: " + message)
        self.finish.set()

    def read_fits(self):
        for line in self.align.stdout:
            try:
                fit = json.loads(line)
            except ValueError:
                continue
            with self.mu:
                self.fits[fit["panel"]] = fit
        self.finish.set()       # ft-align ends when every display is locked, or if it fails

    def run(self):
        if not os.access(CAMD, os.X_OK) or not os.access(FT_ALIGN, os.X_OK):
            return self.fail("alignment isn't built here: run align/build.sh")
        if subprocess.run(["pgrep", "-x", "ft-camd"], capture_output=True, check=False).returncode != 0:
            caps = subprocess.run(["getcap", CAMD], capture_output=True, text=True, check=False).stdout
            if "cap_sys_ptrace" not in caps:
                return self.fail("the cameras need permission once: run hands/run.sh caps in a terminal")
            self.camd = subprocess.Popen([CAMD, "--status", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        spec = f"/tmp/ft-align-spec-{os.getuid()}.json"
        if self.shared:
            code, out, err = ft_layout.run_stream("monitors", self.host["address"])
            if code:
                return self.fail(f"can't list this computer's monitors: {err.strip() or out.strip()}")
            try:
                tags = windows_tags(self.displays, json.loads(out))
            except RuntimeError as e:
                return self.fail(str(e))
            starters = self.displays[:1]
        else:
            tags = {n: first_tag(d, i) for i, (n, d) in enumerate(self.displays)}
            starters = self.displays
        for number, display in starters:
            if not self.switch(number, display, APP):
                return self.fail(f"{display.get('label') or display['id']} didn't start the markers: "
                                 "run this computer's host setup again")
        with open(spec, "w") as f:
            json.dump({"displays": [spec_entry(n, d, tags[n]) for n, d in self.displays]}, f)
        self.align = subprocess.Popen([IN_BOX, FT_ALIGN, "run", spec], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, bufsize=1)
        threading.Thread(target=self.read_fits, daemon=True).start()
        with self.mu:
            self.state = "aligning"
        locks = {n: AutoLock(not d.get("physical")) for n, d in self.displays}
        end = time.time() + TIME_LIMIT_S
        while time.time() < end and not self.finish.wait(0.25):
            with self.mu:
                ready = [n for n, fit in self.fits.items() if n not in self.locked and locks[n].update(fit, time.time())]
            for number in ready:
                self.lock(number)

    def lock(self, number):
        """Freezes a display where it is, and gives it its stream back."""
        with self.mu:
            fit = self.fits.get(number) or {}
            if number in self.locked or "shown_mm" not in fit or self.state != "aligning":
                return False
            self.locked.add(number)
        self.align.stdin.write(f"lock {number}\n")
        self.align.stdin.flush()
        if not self.shared:     # one app shows them all: the streams change back once, at the end
            threading.Thread(target=self.restore, args=(number,), daemon=True).start()
        return True

    def restore(self, number):
        display = dict(self.displays)[number]
        with self.mu:
            if number in self.restored:
                return
            self.restored.add(number)
        try:
            self.switch(number, display, display["app"])
        except (OSError, RuntimeError, ft_layout.NoAnswer) as e:
            ft_layout.log(f"alignment: panel {number}: {e}")

    def keep_sizes(self):
        layout = ft_layout.load_layout()
        changed = False
        for number, _, d in ft_layout.remote_displays(layout):
            fit = self.fits.get(number) or {}
            if number in self.fits and not d.get("physical") and fit.get("shown_mm", 1e9) < MEASURED_BELOW_MM \
                    and fit.get("spots", 0) >= MEASURED_FROM_SPOTS:
                d["physical"] = {"width_m": round(fit["width_m"], 4), "height_m": round(fit["height_m"], 4)}
                d["metres"] = round(fit["width_m"], 4)
                changed = True
        if changed:
            ft_layout.save_layout(layout)

    def apply_joins(self):
        layout = ft_layout.load_layout()
        ids = {d["id"]: n for n, d in self.displays}
        for a, b in layout.get("align_joins", []):
            if a not in ids or b not in ids:
                continue
            na, nb = ids[a], ids[b]
            fa, fb = self.fits.get(na) or {}, self.fits.get(nb) or {}
            if "matrix" not in fa or "matrix" not in fb:
                continue
            along = [fb["matrix"][i * 4 + 3] - fa["matrix"][i * 4 + 3] for i in range(3)]
            first_is_left = sum(fa["matrix"][i * 4] * along[i] for i in range(3)) > 0
            nl, nr = (na, nb) if first_is_left else (nb, na)
            fl, fr = (fa, fb) if first_is_left else (fb, fa)
            width = (fl["width_m"] + fr["width_m"]) / 2
            try:
                left, right, radius, turn, sag = join_panels(fl["matrix"], fr["matrix"], width, float(layout.get("align_join_radius", 0)))
            except ValueError as e:
                ft_layout.log(f"alignment: can't join {a} and {b}: {e}")
                continue
            for number, pose in ((nl, left), (nr, right)):
                self.sock.ask(f"width {number} {width:.4f}")
                self.sock.ask(f"curve {number} {radius:.4f}")
                self.sock.ask(f"pose {number} " + " ".join(f"{v:.5f}" for v in pose))
            ft_layout.log(f"alignment: joined {a} and {b}: radius {radius:.2f} m, {turn:.1f} degrees across each")

    def close(self):
        """Whatever happened, every display gets its stream back and nothing is left running."""
        with self.mu:
            if self.state != "failed":
                self.state = "finishing"
        if self.align and self.align.poll() is None:
            try:
                self.align.stdin.write("quit\n")
                self.align.stdin.flush()
                self.align.wait(timeout=5)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                self.align.kill()
        if self.shared:
            self.restore(self.displays[0][0])   # quitting the app drops the other panels: they reconnect themselves
            self.restored.update(n for n, _ in self.displays)
        else:
            for number, _ in self.displays:
                self.restore(number)
        end = time.time() + 20
        while time.time() < end and not all(
                (ft_layout.remotes_running(self.sock) or {}).get(n, "").startswith("live") for n, _ in self.displays):
            time.sleep(0.3)
        if self.camd:
            self.camd.terminate()
        if self.state != "failed":
            self.keep_sizes()
            self.apply_joins()
            with self.mu:
                self.state = "done"

    def status(self):
        with self.mu:
            rows = []
            for number, display in self.displays:
                fit = self.fits.get(number) or {}
                rows.append({"panel": number, "label": display.get("label") or display["id"], "locked": number in self.locked,
                             "shown_mm": fit.get("shown_mm"), "hint": hint(fit), "spots": fit.get("spots", 0),
                             "sightings": fit.get("sightings", 0), "width_m": fit.get("width_m")})
            return {"state": self.state, "message": self.message, "host": self.host.get("name") or self.host["address"], "displays": rows}


def choose(layout, host_name):
    """The host to align: the one named, or the one whose displays are connected."""
    groups = {}
    for number, host, display in ft_layout.remote_displays(layout):
        physical = display.get("app") == "Desktop" or display.get("app", "").startswith("display:")   # not a virtual one
        if physical and not display.get("off") and (not host_name or host_name == host.get("name")):
            groups.setdefault(host.get("name") or host["address"], (host, []))[1].append((number, display))
    if not groups:
        raise RuntimeError("no connected monitors to align: connect one in Frametop Remote Displays")
    if len(groups) > 1:
        raise RuntimeError("displays from several computers are connected: name one, with --host")
    return next(iter(groups.values()))


def join_choices(layout):
    """The displays that could join, neighbours in the list: [{a, b, label, joined}]."""
    joins = [set(j) for j in layout.get("align_joins", [])]
    out = []
    last = None
    for _, host, d in ft_layout.remote_displays(layout):
        if last and last[0] is host and not d.get("off") and not last[1].get("off"):
            a, b = last[1], d
            out.append({"a": a["id"], "b": b["id"], "joined": {a["id"], b["id"]} in joins,
                        "label": f"{a.get('label') or a['id']} and {d.get('label') or d['id']}"})
        last = (host, d)
    return out


def set_join(layout, a, b, on):
    joins = [j for j in layout.get("align_joins", []) if not set(j) & {a, b}]
    layout["align_joins"] = joins + ([[a, b]] if on else [])


def serve(session):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(SOCKET)
    server.settimeout(0.5)

    def loop():
        while True:
            try:
                data, peer = server.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                return
            words = data.decode().split()
            reply = {"ok": True}
            if words[:1] == ["status"]:
                reply = session.status()
            elif words[:2] == ["lock", "all"]:
                for number, _ in session.displays:
                    session.lock(number)
            elif words[:1] == ["lock"] and len(words) == 2 and words[1].isdigit():
                reply = {"ok": session.lock(int(words[1]))}
            elif words[:1] == ["stop"]:
                session.finish.set()
            if peer:
                try:
                    server.sendto(json.dumps(reply).encode(), peer)
                except OSError:
                    pass

    threading.Thread(target=loop, daemon=True).start()
    return server


def ask(text):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    client.bind("")
    client.settimeout(3)
    try:
        client.sendto(text.encode(), SOCKET)
        return json.loads(client.recv(8192).decode())
    except (OSError, socket.timeout) as e:
        raise RuntimeError("no alignment is running") from e


def start(host_name=None):
    layout = ft_layout.load_layout()
    host, displays = choose(layout, host_name)
    session = Session(host, displays)
    try:
        server = serve(session)
    except OSError as e:
        raise RuntimeError("an alignment is already running") from e
    signal.signal(signal.SIGTERM, lambda *_: session.finish.set())
    signal.signal(signal.SIGHUP, lambda *_: session.finish.set())
    last = 0.0
    worker = threading.Thread(target=session.run, daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(1)
            if time.time() - last >= 5:
                last = time.time()
                status = session.status()
                if status["state"] == "aligning":
                    ft_layout.log("  ".join(f"{r['panel']}: {'locked' if r['locked'] else r['shown_mm'] if r['shown_mm'] is not None else '-'}"
                                            for r in status["displays"]))
    except KeyboardInterrupt:
        session.finish.set()
        worker.join(5)
    finally:
        session.close()
        time.sleep(1)   # one more status for whoever is watching
        server.close()
    status = session.status()
    ft_layout.log(f"alignment: {status['state']}{': ' + status['message'] if status['message'] else ''}")
    return 0 if status["state"] == "done" else 1


def command(args):
    """ft-layout align [start [--host NAME]] | toggle | status | lock N|all | stop | join ID ID | unjoin"""
    what = args[0] if args else "start"
    if what == "start":
        return start(args[args.index("--host") + 1] if "--host" in args else None)
    if what == "toggle":     # for a menu entry or a mapped button: the one control there is in the headset
        try:
            ask("stop")
        except RuntimeError:
            return start()
        return 0
    if what == "status":
        print(json.dumps(ask("status"), indent=1))
    elif what == "lock" and len(args) == 2:
        print(json.dumps(ask("lock " + args[1])))
    elif what == "stop":
        print(json.dumps(ask("stop")))
    elif what == "join" and len(args) == 3:
        layout = ft_layout.load_layout()
        set_join(layout, args[1], args[2], True)
        ft_layout.save_layout(layout)
    elif what == "unjoin":
        layout = ft_layout.load_layout()
        layout.pop("align_joins", None)
        ft_layout.save_layout(layout)
    else:
        raise RuntimeError(command.__doc__)
    return 0
