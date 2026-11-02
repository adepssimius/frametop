#!/usr/bin/env python3
"""On the headset: switches one remote panel from its stream to a marker app and back, timing each step, and
watches the other panels of that host. It tests whether a host can show alignment markers through an app.
Usage: app_switch.py PANEL [--app FrametopAlign] [--hold 20] [--dry-run]"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.expanduser('~/frametop/layout'))
import ft_layout  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('panel', type=int)
ap.add_argument('--app', default='FrametopAlign')
ap.add_argument('--hold', type=float, default=20)
ap.add_argument('--dry-run', action='store_true')
args = ap.parse_args()

layout = ft_layout.load_layout()
displays = {n: (host, d) for n, host, d in ft_layout.remote_displays(layout)}
if args.panel not in displays:
    sys.exit(f'no panel {args.panel}; these exist: {sorted(displays)}')
host, disp = displays[args.panel]
target = ft_layout.display_target(host, disp)
address, _, port = target.partition(':')
http_port = int(port or 47989)
https = f'https://{address}:{http_port - 5}'    # Sunshine's HTTPS port is its base port less 5
keys = os.path.expanduser('~/.local/share/frametop-stream/' + disp['client'])
w, h = ft_layout.stream_size(*disp.get('size', [2560, 1440]))
rest = f"{int(w)}x{int(h)} {int(disp.get('fps', 60))} {int(disp.get('bitrate', 0))} {ft_layout.remote_size(disp)[0]:.4f}"
others = [n for n, (o, _) in displays.items() if o is host and n != args.panel]
print(f"panel {args.panel}: {disp.get('label') or disp['id']}, client {disp['client']}, target {target}, app {disp['app']}, "
      f"HTTPS {https}, same host's other panels {others}")
if args.dry_run:
    sys.exit(0)

sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
sock.bind('')
sock.settimeout(5)
t0 = time.time()


def log(text):
    print('%6.1f  %s' % (time.time() - t0, text), flush=True)


def ask(cmd):
    sock.sendto(cmd.encode(), '\0ft_screens')
    return sock.recv(8192).decode()


def game():
    out = subprocess.run(['curl', '-s', '-m', '3', f'http://{address}:{http_port}/serverinfo'], capture_output=True, text=True).stdout
    found = re.search(r'<currentgame>(\d+)', out), re.search(r'<state>([^<]*)', out)
    return tuple(f[1] if f else None for f in found)


def cancel():
    uid = open(keys + '/uniqueid.dat').read().strip()
    out = subprocess.run(['curl', '-sk', '-m', '8', '--cert', keys + '/client.pem', '--key', keys + '/key.pem',
                          f'{https}/cancel?uniqueid={uid}&uuid={uuid.uuid4()}'], capture_output=True, text=True)
    return out.stdout[:140].replace('\n', ' ') or f'curl exit {out.returncode}'


def states():
    out = subprocess.run([os.path.expanduser('~/frametop/layout/ft-layout'), 'remote', 'list'], capture_output=True, text=True).stdout
    found = {}
    for line in out.splitlines():
        f = line.split()
        if f and f[0].isdigit():
            found[int(f[0])] = 'live' if ' live ' in line else line[-60:]
    return found


def wait_live(what, limit=30):
    began = time.time()
    while time.time() - began < limit:
        if states().get(args.panel) == 'live':
            log(f'{what}: live after {time.time() - began:.1f} s')
            return True
        time.sleep(0.4)
    log(f'{what}: NOT live after {limit} s: {states().get(args.panel)}')
    return False


def show_others(when):
    now = states()
    log(f'other panels {when}: ' + (', '.join(f'{n} {now.get(n)}' for n in others) or 'none'))


pose = ask(f'get {args.panel}')[:60]
log(f'server before: {game()}')
show_others('before')
log('stop panel: ' + ask(f'remote {args.panel} stop'))
log('cancel: ' + cancel())
log(f'server after cancel: {game()}')
show_others('after cancel')
time.sleep(1)
log('start marker app: ' + ask(f"remote {args.panel} start {disp['client']} {target} {args.app} {rest} Align test"))
wait_live('marker app')
log(f'server with the app: {game()}')
show_others('with the app')
log(f'CHECK NOW: markers on screen for {args.hold:.0f} s')
time.sleep(args.hold)
log('stop panel: ' + ask(f'remote {args.panel} stop'))
log('cancel: ' + cancel())
log(f'server after cancel: {game()}')
show_others('after the second cancel')
log('CHECK NOW: the markers should be gone')
time.sleep(5)
label = f"{host.get('name') or host['address']}: {disp.get('label') or disp['id']}"
log('start its stream: ' + ask(f"remote {args.panel} start {disp['client']} {target} {disp['app']} {rest} {label}"))
wait_live('its stream')
time.sleep(3)
show_others('at the end')
log('panel moved: ' + ('no' if ask(f'get {args.panel}')[:60] == pose else 'YES'))
