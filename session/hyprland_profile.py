#!/usr/bin/env python3
"""Open a saved Hyprland profile's windows on their screens.

  hyprland_profile.py start          the profile the desktop starts in
  hyprland_profile.py open NAME      that profile
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import hyprland_layout as layout


def hypr_env():
    env = os.environ.copy()
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    route = Path(f"/run/user/{os.getuid()}") / "frametop-hyprland.route"
    try:
        for line in route.read_text(encoding="utf-8").splitlines():
            if line.startswith("runtime="):
                runtime = line.split("=", 1)[1]
    except OSError:
        pass
    env["XDG_RUNTIME_DIR"] = runtime
    hypr = Path(runtime) / "hypr"
    if hypr.is_dir():
        names = sorted(p.name for p in hypr.iterdir())
        if names:
            env["HYPRLAND_INSTANCE_SIGNATURE"] = names[0]
    return env, runtime


def hypr_json(kind, env):
    try:
        proc = subprocess.run(["hyprctl", kind, "-j"], capture_output=True, text=True,
                              check=False, env=env, timeout=3)
        data = json.loads(proc.stdout or "null")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    return data if isinstance(data, list) else []


def output_map(runtime):
    try:
        data = json.loads((Path(runtime) / "frametop-output-map.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    mapping = data.get("mapping") if isinstance(data, dict) else {}
    return mapping if isinstance(mapping, dict) else {}


def open_windows(name):
    """Move or launch a profile's windows. Does not place the screens."""
    if not name:
        return 0
    data = layout.load()
    env, runtime = hypr_env()
    clients = hypr_json("clients", env)
    for expr in layout.open_profile_evals(data, name, output_map(runtime), clients):
        subprocess.run(["hyprctl", "eval", expr], check=False, env=env, timeout=3)
    return 0


def open_named(name):
    data = layout.load()
    if not name:
        name = data.get("default_profile") or ""
    if name:
        try:
            layout.apply_profile(name)
        except RuntimeError as exc:
            print(f"frametop: {exc}", file=sys.stderr)
    if not name:
        return 0
    return open_windows(name)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "start"
    if cmd == "start":
        return open_named("")
    if cmd == "open" and len(argv) >= 3:
        return open_named(" ".join(argv[2:]))
    print("usage: hyprland_profile.py start | open NAME", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
