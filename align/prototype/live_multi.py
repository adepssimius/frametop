"""Live alignment of a test panel to every Mac display at once. Each display shows its own markers (its own IDs),
a green grid and its error; the headset shows a magenta grid per display. Click a display to lock it.
Usage: live_multi.py [--seconds N] [--check]     (--check only writes and verifies the images)"""
import argparse
import json
import os
import queue
import struct
import subprocess
import sys
import threading
import time
import zlib

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import live_core as L

ap = argparse.ArgumentParser()
ap.add_argument('--seconds', type=float, default=180)
ap.add_argument('--hold', type=float, default=15)
ap.add_argument('--check', action='store_true')
args = ap.parse_args()

SHOW_FACTOR = 4.0
READY_MM = 5.0
SCALE = 0.2784 / 0.2724   # measured pitch vs spec on the right OMEN: assume the same for the built-in display
SSH = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-i', os.path.expanduser('~/.ssh/claude_ed25519'),
       '-o', 'IdentityAgent=none', '-o', 'ConnectTimeout=8', 'steamos@frame.local']
DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
GREEN, WHITE, YELLOW, GREY = (0, 255, 0), (255, 255, 255), (0, 255, 255), (180, 180, 180)


class Screen:
    def __init__(self, name, x, w, h, pitch, first_id, grid, panel):
        self.name, self.x, self.w, self.h, self.pitch, self.grid, self.panel = name, x, w, h, pitch, grid, panel
        self.moved = False
        self.ids = list(range(first_id, first_id + 4))
        self.tag = round(h * 0.43)
        self.margin = round(h * 0.056)
        self.quiet = round(h * 0.031)
        m, t = self.margin, self.tag
        places = [(m, m), (w - m - t, m), (m, h - m - t), (w - m - t, h - m - t)]
        self.corners = {str(i): [[x0, y0], [x0 + t, y0], [x0 + t, y0 + t], [x0, y0 + t]] for i, (x0, y0) in zip(self.ids, places)}
        self.base = self.draw_grid(with_tags=True)
        self.plain = self.draw_grid(with_tags=False)
        self.solver = None
        self.lines = [('STARTING...', 2.4, WHITE)]
        self.version = 1
        self.shown_version = 0
        self.locked = False
        self.best = None
        self.log = []
        self.sightings = 0
        self.view = None

    def draw_grid(self, with_tags):
        w, h, g = self.w, self.h, self.grid
        im = np.zeros((h, w, 3), np.uint8)
        for x in range(0, w + 1, g):
            cv2.line(im, (min(x, w - 1), 0), (min(x, w - 1), h - 1), GREEN, 2 if x % (g * 4) else 5)
        for y in range(0, h + 1, g):
            cv2.line(im, (0, min(y, h - 1)), (w - 1, min(y, h - 1)), GREEN, 2 if y % (g * 4) else 5)
        cv2.rectangle(im, (0, 0), (w - 1, h - 1), GREEN, 10)
        if with_tags:
            for i in self.ids:
                x0, y0 = self.corners[str(i)][0]
                t, q = self.tag, self.quiet
                im[y0 - q:y0 + t + q, x0 - q:x0 + t + q] = 255
                im[y0:y0 + t, x0:x0 + t] = cv2.cvtColor(cv2.aruco.generateImageMarker(DICT, i, t), cv2.COLOR_GRAY2BGR)
        return im

    def overlay_image(self):
        w, h, g = self.w, self.h, self.grid
        col = (255, 0, 255, 255)
        im = np.zeros((h, w, 4), np.uint8)
        for x in range(0, w + 1, g):
            cv2.line(im, (min(x, w - 1), 0), (min(x, w - 1), h - 1), col, 2 if x % (g * 4) else 5)
        for y in range(0, h + 1, g):
            cv2.line(im, (0, min(y, h - 1)), (w - 1, min(y, h - 1)), col, 2 if y % (g * 4) else 5)
        cv2.rectangle(im, (0, 0), (w - 1, h - 1), col, 10)
        return im

    def render(self):
        im = (self.plain if self.locked else self.base).copy()
        m = self.margin + self.tag + self.quiet + 15
        x0, x1 = m, self.w - m
        y0, y1 = int(self.h * 0.30), int(self.h * 0.70)
        k = self.h / 1440
        cv2.rectangle(im, (x0, y0), (x1, y1), (0, 0, 0), -1)
        y = y0 + int(30 * k)
        for text, scale, color in self.lines:
            s = scale * k
            th = max(2, int(s * 2.4))
            (tw, th_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, s, th)
            if tw > x1 - x0 - 20:
                s *= (x1 - x0 - 20) / tw
                th = max(2, int(s * 2.4))
                (tw, th_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, s, th)
            y += th_h + int(26 * k)
            cv2.putText(im, text, ((x0 + x1 - tw) // 2, y), cv2.FONT_HERSHEY_SIMPLEX, s, color, th, cv2.LINE_AA)
        return im

    def say(self, lines):
        self.lines = lines
        self.version += 1


SCREENS = [Screen('OMEN (1), right', -2560, 2560, 1440, 0.2784e-3, 0, 160, 103),
           Screen('OMEN (2), left', -5120, 2560, 1440, 0.2784e-3, 4, 160, 102),
           Screen('Built-in', 0, 3024, 1964, 0.1e-3 * SCALE, 8, 320, 101)]

det = L.make_detector()
for i, s in enumerate(SCREENS):
    cv2.imwrite(f'{HERE}/multi_overlay_{i}.png', s.overlay_image())
    _, ids, _ = cv2.aruco.ArucoDetector(DICT, cv2.aruco.DetectorParameters()).detectMarkers(cv2.cvtColor(s.render(), cv2.COLOR_BGR2GRAY))
    found = [] if ids is None else sorted(ids.flatten().tolist())
    print(s.name, 'tags in its image', found, 'expected', s.ids, 'width m %.4f' % (s.w * s.pitch))
    assert found == s.ids
if args.check:
    sys.exit(0)

import AppKit
import Foundation

T = int(args.seconds + 15)
remote = (f"rm -f /tmp/ft-poselog/live.csv; "
          f"(setsid nohup timeout {T} ~/frametop/hands/build/ft-camd --status 30 > /tmp/ft-camd-test.log 2>&1 < /dev/null &); "
          f"(cd ~/frametop; setsid nohup timeout {T} scripts/in-box /tmp/ft-poselog/ft-poselog /tmp/ft-poselog/live.csv {T} "
          f"> /tmp/ft-poselog/log.txt 2>&1 < /dev/null &); "
          f"exec timeout {T} python3 /tmp/ft-stream.py /tmp/ft-poselog/live.csv {T} 6")
stream = subprocess.Popen(SSH + ['-n', remote], stdout=subprocess.PIPE, stderr=open(HERE + '/stream.err', 'w'), bufsize=1 << 20)
overlay = subprocess.Popen(SSH + ['exec python3 -u /tmp/ft-panelctl.py'], stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL, stderr=open(HERE + '/overlay.err', 'w'), text=True, bufsize=1)
poses = L.Poses()
frames = queue.Queue()
stats = dict(frames_in=0, frames_tag=0, dropped=0)
finished = threading.Event()
hold_until = [None]


def read_exact(n):
    b = stream.stdout.read(n)
    if b is None or len(b) < n:
        raise EOFError
    return b


def reader():
    try:
        while True:
            kind = read_exact(1)
            if kind == b'P':
                n = struct.unpack('<I', read_exact(4))[0]
                poses.add_rows([np.array(l.split(b','), float) for l in read_exact(n).splitlines() if l.count(b',') == 13])
            elif kind == b'F':
                cam, t, w, h, n = struct.unpack('<BQIII', read_exact(21))
                frames.put((cam, t, w, h, read_exact(n)))
            else:
                raise ValueError('stream out of step: %r' % kind)
    except EOFError:
        pass
    finally:
        frames.put(None)


def send_overlay(i, s, M):
    try:
        if not s.moved:
            s.moved = True
            overlay.stdin.write('width %d %.4f\ncurve %d 0\n' % (s.panel, s.w * s.pitch, s.panel))
        overlay.stdin.write('pose %d %s\n' % (s.panel, ' '.join('%.5f' % v for v in M.ravel())))
        overlay.stdin.flush()
    except (BrokenPipeError, ValueError, OSError):
        pass


def hint(r, shown):
    x, y, z = r['range_mm']
    if shown < READY_MM:
        return 'GOOD. CLICK HERE TO LOCK', GREEN
    if r['dist'] > 0.95:
        return 'LEAN CLOSER', YELLOW
    if y < 150:
        return 'MOVE UP AND DOWN', YELLOW
    if x < 200:
        return 'MOVE SIDE TO SIDE', YELLOW
    return 'KEEP MOVING SLOWLY', YELLOW


def worker():
    cal = L.load_calib()
    for s in SCREENS:
        s.solver = L.Solver(cal, dict(corners=s.corners), s.pitch, s.w, s.h)
        s.say([('LOOK AT THIS SCREEN', 2.4, YELLOW), ('AND MOVE YOUR HEAD SLOWLY', 2, YELLOW)])
    t_start = time.time()
    turn = 0
    next_solve = 0
    while not finished.is_set():
        try:
            item = frames.get(timeout=0.5)
        except queue.Empty:
            continue
        if item is None:
            return
        cam, t, w, h, z = item
        stats['frames_in'] += 1
        head = None
        for _ in range(10):
            head = poses.at(t - L.OFF_NS)
            if head is not None:
                break
            time.sleep(0.03)
        if head is None:
            continue
        im = np.frombuffer(zlib.decompress(z), np.uint8).reshape(h, w)
        c, ids, _ = det.detectMarkers(im)
        if ids is not None:
            stats['frames_tag'] += 1
            tags = {int(i): cc[0].astype(float) for cc, i in zip(c, ids.flatten())}
            for s in SCREENS:
                n = sum(i in tags for i in s.ids)
                if n and not s.locked:
                    s.sightings += n
                    s.solver.add(cam, head, tags)
        now = time.time()
        if now < next_solve:
            continue
        # One display per pass, so none of them holds up the frames.
        open_screens = [i for i, s in enumerate(SCREENS) if not s.locked and s.solver.obs]
        if not open_screens:
            continue
        i = open_screens[turn % len(open_screens)]
        turn += 1
        s = SCREENS[i]
        r = s.solver.solve(max_frames=100)
        next_solve = time.time() + 0.1
        if r is None or s.locked:
            continue
        M = s.solver.overlay_matrix(r['q'])
        shown = r['sd_mm'] * SHOW_FACTOR
        if shown < 100:   # the first few estimates can be far off
            send_overlay(i, s, M)
        s.best = dict(shown_mm=shown, frames=r['frames'], rms=r['rms'], range_mm=r['range_mm'].tolist(), dist=r['dist'],
                      t=now - t_start, matrix=M.tolist(), q=r['q'].tolist())
        s.log.append((now - t_start, shown, r['change_mm'], r['frames']))
        text, color = hint(r, shown)
        s.say([('ERROR ABOUT', 1.6, GREY), ('%.0f mm' % shown, 6, GREEN if shown < READY_MM else WHITE), (text, 1.7, color)])


class ClickView(AppKit.NSImageView):
    def acceptsFirstMouse_(self, event):
        return True

    def mouseDown_(self, event):
        on_click(self.screen_index)


def on_click(i):
    s = SCREENS[i]
    if s.locked:
        if all(x.locked or x.best is None for x in SCREENS):
            finished.set()
        return
    if s.best is None:
        return
    s.locked = True
    s.say([('LOCKED', 3, GREEN), ('ERROR ABOUT %.0f mm' % s.best['shown_mm'], 1.8, WHITE)])
    if all(x.locked for x in SCREENS):
        hold_until[0] = time.time() + args.hold
        for x in SCREENS:
            x.say(x.lines[:2] + [('CLICK AGAIN TO CLOSE', 1.4, GREY)])


def nsimage(im, size):
    ok, buf = cv2.imencode('.png', im)
    img = AppKit.NSImage.alloc().initWithData_(Foundation.NSData.dataWithBytes_length_(buf.tobytes(), len(buf)))
    img.setSize_(size)
    return img


def cleanup():
    finished.set()
    try:
        overlay.stdin.close()
        overlay.wait(timeout=10)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    for p in (stream, overlay):
        try:
            p.terminate()
        except OSError:
            pass
    subprocess.run(SSH + ['-n', 'pkill -f "[f]t-stream.py"; pkill -x ft-camd; pkill -x ft-poselog; pkill -f "[f]t-panelctl.py"; rm -f /tmp/ft-poselog/live.csv'],
                   timeout=25, check=False)
    print('frames in %d, with tags %d' % (stats['frames_in'], stats['frames_tag']))
    out = {}
    for s in SCREENS:
        out[s.name] = dict(s.best or {}, locked=s.locked, sightings=s.sightings, log=s.log)
        print('%s: locked %s, tag sightings %d' % (s.name, s.locked, s.sightings), end='')
        if s.best:
            b = s.best
            print(', last figure %.1f mm at %.1f s, frames %d, rms %.2f px, dist %.2f m, range mm %s' % (
                b['shown_mm'], b['t'], b['frames'], b['rms'], b['dist'], np.round(b['range_mm']).tolist()))
            hit = [e for e in s.log if e[1] < READY_MM]
            print('   first estimate at %.1f s; first under %g mm: %s' % (s.log[0][0], READY_MM, 'at %.1f s' % hit[0][0] if hit else 'never'))
        else:
            print(', no estimate')
    json.dump(out, open(HERE + '/multi_result.json', 'w'))
    sys.stdout.flush()


class Delegate(AppKit.NSObject):
    def tick_(self, timer):
        now = time.time()
        if hold_until[0] is not None and now > hold_until[0]:
            finished.set()
        if hold_until[0] is None and now > self.deadline:
            finished.set()
        for s in SCREENS:
            if s.shown_version != s.version:
                s.shown_version = s.version
                s.view.setImage_(nsimage(s.render(), s.size))
        if finished.is_set():
            for w in self.windows:
                w.orderOut_(None)
            cleanup()
            AppKit.NSApp.terminate_(None)


app = AppKit.NSApplication.sharedApplication()
app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
windows = []
for i, s in enumerate(SCREENS):
    target = next(x for x in AppKit.NSScreen.screens() if x.frame().origin.x == s.x)
    fr = target.frame()
    win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(fr, 0, AppKit.NSBackingStoreBuffered, False)
    win.setLevel_(1000)
    win.setOpaque_(True)
    s.size = fr.size
    view = ClickView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, fr.size.width, fr.size.height))
    view.screen_index = i
    view.setImageScaling_(AppKit.NSImageScaleAxesIndependently)
    s.view = view
    win.setContentView_(view)
    win.setFrame_display_(fr, True)
    win.orderFrontRegardless()
    windows.append(win)

delegate = Delegate.alloc().init()
delegate.windows = windows
delegate.deadline = time.time() + args.seconds
Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.15, delegate, 'tick:', None, True)
threading.Thread(target=reader, daemon=True).start()
threading.Thread(target=worker, daemon=True).start()
app.run()
