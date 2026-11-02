#!/usr/bin/env python3
"""Runs on the headset, with no numpy: streams side camera frames and head poses to stdout.
Records: b'F' + <BQIII cam dqbuf_ns w h len + zlib frame | b'P' + <I len + CSV lines.
Usage: stream.py POSES.csv SECONDS FRAME_RATE"""
import mmap
import os
import struct
import sys
import time
import zlib

poses_path, seconds, rate = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
RING = '/run/user/%d/frametop-hands/cam-ring' % os.getuid()
HDR = struct.Struct('<8sIIIIQqQ16x')
CAM = struct.Struct('<32s32siIIIIIQQQQQ32x')
SLOT = struct.Struct('<QQQQQIf16x')
LATEST_OFF = 32 + 32 + 4 * 6 + 8 * 2
out = sys.stdout.buffer

end = time.time() + 20
while not (os.path.exists(RING) and os.path.getsize(RING) > 0 and os.path.exists(poses_path)):
    if time.time() > end:
        sys.exit('camera ring or pose log never appeared')
    time.sleep(0.1)
time.sleep(0.5)

fd = os.open(RING, os.O_RDONLY)
m = mmap.mmap(fd, 0, mmap.MAP_SHARED, mmap.PROT_READ)
magic, version, _, ncams, _, _, _, _ = HDR.unpack_from(m, 0)
assert magic == b'FHRING01' and version == 1
cams = []
for i in range(min(ncams, 2)):
    _, _, _, _, w, h, stride, nslots, slot_off, slot_bytes, _, _, _ = CAM.unpack_from(m, HDR.size + i * CAM.size)
    cams.append((i, w, h, stride, nslots, slot_off, slot_bytes, HDR.size + i * CAM.size + LATEST_OFF))

poses = open(poses_path, 'rb')
partial = b''
end = time.time() + seconds
last = [0, 0]
while time.time() < end:
    tick = time.time()
    chunk = poses.read()
    if chunk:
        chunk = partial + chunk
        cut = chunk.rfind(b'\n') + 1
        partial = chunk[cut:]
        if cut:
            out.write(b'P' + struct.pack('<I', cut) + chunk[:cut])
    for i, w, h, stride, nslots, slot_off, slot_bytes, latest_off in cams:
        n = struct.unpack_from('<Q', m, latest_off)[0]
        if n == 0 or n == last[i]:
            continue
        off = slot_off + (n % nslots) * slot_bytes
        fields = SLOT.unpack_from(m, off)
        if fields[0] != 2 * n + 2:
            continue
        start = off + SLOT.size
        rows = b''.join(m[start + y * stride:start + y * stride + w] for y in range(h))
        if struct.unpack_from('<Q', m, off)[0] != fields[0]:
            continue
        last[i] = n
        z = zlib.compress(rows, 1)
        out.write(b'F' + struct.pack('<BQIII', i, fields[3], w, h, len(z)) + z)
    out.flush()
    time.sleep(max(0, 1 / rate - (time.time() - tick)))
