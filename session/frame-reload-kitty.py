#!/usr/bin/env python3
"""Tell Kitty windows in this nested session to reload their colors."""
import os
import signal
from pathlib import Path

runtime = os.environ.get("XDG_RUNTIME_DIR", "")
if runtime and os.path.isabs(runtime):
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            args = (proc / "cmdline").read_bytes().split(b"\0")
            env = (proc / "environ").read_bytes().split(b"\0")
            if (args and os.path.basename(os.fsdecode(args[0])) == "kitty"
                    and os.fsencode("XDG_RUNTIME_DIR=" + runtime) in env):
                os.kill(int(proc.name), signal.SIGUSR1)
        except (OSError, ValueError):
            pass
