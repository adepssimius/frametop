#!/usr/bin/env python3
"""Stop only video wallpapers belonging to this nested desktop runtime."""
import os
import signal
import sys
from pathlib import Path

runtime = os.environ.get("XDG_RUNTIME_DIR", "")
if not runtime or not os.path.isabs(runtime):
    sys.exit("frametop: no session runtime; refusing to stop wallpapers")
monitor = sys.argv[1] if len(sys.argv) > 1 else ""
for proc in Path("/proc").iterdir():
    if not proc.name.isdigit():
        continue
    try:
        args = (proc / "cmdline").read_bytes().split(b"\0")
        if not args or os.path.basename(os.fsdecode(args[0])) != "mpvpaper":
            continue
        env = (proc / "environ").read_bytes().split(b"\0")
        if os.fsencode("XDG_RUNTIME_DIR=" + runtime) not in env:
            continue
        if monitor and os.fsencode(monitor) not in args[1:]:
            continue
        os.kill(int(proc.name), signal.SIGTERM)
    except (OSError, ValueError):
        continue
