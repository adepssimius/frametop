#!/usr/bin/env python3
"""Runs on the headset: passes lines from stdin to ft-screens' control socket.
A line is a ft-screens command, or "restore N" to put panel N back as panels_before.json has it."""
import json
import socket
import sys

BEFORE = '/tmp/ft-poselog/panels_before.json'
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.bind('')
s.settimeout(3)


def ask(cmd):
    try:
        s.sendto(cmd.encode(), '\0ft_screens')
        reply = s.recv(8192).decode()
    except OSError as e:
        reply = 'error %s' % e
    if not reply.startswith('ok'):
        print('%s -> %s' % (cmd.split(' ')[0:2], reply), file=sys.stderr, flush=True)
    return reply


def restore(n):
    f = json.load(open(BEFORE))[str(n)].split()[1:]
    v = [float(x) for x in f[:15]]
    pos, X, Y, Z, width, curve = v[:3], v[3:6], v[6:9], v[9:12], v[12], float(f[14])
    ask('width %d %.4f' % (n, width))
    ask('curve %d %.3f' % (n, curve))
    rows = [(X[i], Y[i], Z[i], pos[i]) for i in range(3)]
    ask('pose %d %s' % (n, ' '.join('%.5f' % x for r in rows for x in r)))
    if f[15] != 'none':
        ask('pin %d %s %s' % (n, f[15], ' '.join(f[16:28])))


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    if line.startswith('restore '):
        restore(int(line.split()[1]))
    else:
        reply = ask(line)
        if line.startswith('get ') or line == 'screens':
            print(reply, flush=True)
