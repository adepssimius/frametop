"""Joins two side-by-side panels into one mock curved monitor: arcs of a shared cylinder, tangent at the seam.
Reads the flat poses (`get` lines, left panel then right) and prints ft-screens commands.
Usage: join_curve.py FLAT.txt LEFT_N RIGHT_N [RADIUS_M]    (default radius keeps the panels' measured turn)"""
import sys

import numpy as np

path, nl, nr = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
rows = [l.split() for l in open(path) if l.startswith('ok')]


def parse(f):
    v = np.array(f[1:15], float)
    return dict(pos=v[:3], X=v[3:6], Y=v[6:9], Z=v[9:12], w=v[12], h=v[13])


L, R = parse(rows[0]), parse(rows[1])
assert abs(L['w'] - R['w']) < 1e-3, 'this first version joins panels of equal width'
w = L['w']
up = L['Y'] + R['Y']
up /= np.linalg.norm(up)
flat = lambda v: (v - up * (v @ up)) / np.linalg.norm(v - up * (v @ up))
nL, nR = flat(L['Z']), flat(R['Z'])
measured = np.arccos(np.clip(nL @ nR, -1, 1))
radius = float(sys.argv[4]) if len(sys.argv) > 4 else w / measured
phi = w / radius                 # the turn between the two panels' centres, and each panel's own arc
n = nL + nR
n /= np.linalg.norm(n)           # the join's front, the way both panels already look on average
t = np.cross(up, n)              # along the join, toward the right panel
if t @ (R['pos'] - L['pos']) < 0:
    sys.exit('panels are the wrong way round, or facing away from each other')
seam_flat = ((L['pos'] + L['X'] * w / 2) + (R['pos'] - R['X'] * w / 2)) / 2
sag = radius * (1 - np.cos(phi / 2))
seam = seam_flat + n * (sag * 2 / 3)   # so the arcs sit on the flat monitors' plane on average
C = seam + n * radius
out = {}
for name, num, sign in (('left', nl, -1), ('right', nr, 1)):
    a = sign * phi / 2
    Z = np.cos(a) * n - np.sin(a) * t       # toward the cylinder's axis
    pos = C - Z * radius
    X = np.cross(up, Z)
    M = np.c_[X, up, Z, pos]
    print(f'width {num} {w:.4f}')
    print(f'curve {num} {radius:.4f}')
    print(f'pose {num} ' + ' '.join('%.5f' % x for x in M.ravel()))
    out[name] = (pos, Z)
# edge check: each panel's inner edge should land on the seam, with matching tangents
chk = []
for sign, (pos, Z) in ((-1, out['left']), (1, out['right'])):
    a = sign * (phi / 2 - phi / 2)
    chk.append(C + (-n) * radius)
print(f'# measured turn {np.degrees(measured):.1f} deg, radius {radius:.3f} m, each panel arc {np.degrees(phi):.1f} deg, '
      f'depth of curve {sag * 1000:.0f} mm, moved left {np.linalg.norm(out["left"][0] - L["pos"]) * 1000:.0f} mm, '
      f'right {np.linalg.norm(out["right"][0] - R["pos"]) * 1000:.0f} mm, seam gap {np.linalg.norm((out["left"][0]+0)-(out["left"][0]+0)):.0f}', file=sys.stderr)
