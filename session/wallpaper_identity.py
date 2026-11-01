#!/usr/bin/env python3
"""Per-monitor wallpaper keys for the Hyprland session.

Adapted from end-4/dots-hyprland pull 2245 by Sevilze (GPL-3.0-or-later):
one image per monitor, a global image when that mode is off, and the last
chosen image still drives the shared Material You palette. Assignments are
stored under the Frametop screen id (hypr-N) from the output map, not under
Aquamarine's WAYLAND-N creation counter.
"""
import json
import os
import sys
from pathlib import Path


def map_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "frametop-output-map.json"


def config_path():
    root = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(root) / "illogical-impulse" / "config.json"


def assignments_path(config_file=None):
    """Sidecar for per-monitor images.

    The shell rewrites illogical-impulse/config.json from its own model, and
    that rewrite drops wallpapersByMonitor. Assignments live beside it.
    """
    config_file = Path(config_file) if config_file else config_path()
    return config_file.parent / "wallpapers-by-monitor.json"


def load_mapping(path=None):
    path = Path(path) if path else map_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    mapping = data.get("mapping") if isinstance(data, dict) else None
    if not isinstance(mapping, dict):
        return {}
    return {str(name): str(ident) for name, ident in mapping.items() if name and ident}


def assignment_key(monitor_name, mapping):
    """Stable id for a live output. An unknown name is stored as itself."""
    if not monitor_name:
        return ""
    return str(mapping.get(monitor_name) or monitor_name)


def effective(entries, mapping, monitors, global_path, enabled):
    """Live monitor name -> the image that monitor should show.

    `enabled` false paints `global_path` on every monitor and leaves the
    per-monitor list untouched. A stored hypr-N follows the output that
    currently claims that id.
    """
    by_key = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("monitor")
        path = entry.get("path")
        if key and path:
            by_key[str(key)] = entry
    result = {}
    for name in monitors or []:
        if not enabled:
            if global_path:
                result[name] = {"path": global_path}
            continue
        ident = assignment_key(name, mapping)
        entry = by_key.get(ident) or by_key.get(name) or {}
        path = entry.get("path") or global_path
        if not path:
            continue
        data = {"path": path}
        first = entry.get("workspaceFirst")
        last = entry.get("workspaceLast")
        if first is not None and last is not None:
            data["workspaceFirst"] = int(first)
            data["workspaceLast"] = int(last)
        thumb = entry.get("thumbnail") or ""
        if thumb:
            data["thumbnail"] = thumb
        result[name] = data
        ident = assignment_key(name, mapping)
        if ident and ident not in result:
            result[ident] = data
    return result


def upsert(entries, key, path, first, last, thumbnail=""):
    kept = [entry for entry in (entries or []) if isinstance(entry, dict) and entry.get("monitor") != key]
    item = {
        "monitor": key,
        "path": path,
        "workspaceFirst": int(first),
        "workspaceLast": int(last),
    }
    if thumbnail:
        item["thumbnail"] = thumbnail
    kept.append(item)
    return kept


def load_config(config_file=None):
    config_file = Path(config_file) if config_file else config_path()
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = {}
    return config if isinstance(config, dict) else {}


def _read_sidecar(config_file=None):
    side = assignments_path(config_file)
    try:
        data = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data


def load_entries(config_file=None):
    """Sidecar first. The list inside config.json is only the old location."""
    data = _read_sidecar(config_file)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("wallpapersByMonitor"), list):
        return data["wallpapersByMonitor"]
    background = (load_config(config_file).get("background") or {})
    entries = background.get("wallpapersByMonitor") or []
    return entries if isinstance(entries, list) else []


def multi_enabled(config_file=None):
    """The sidecar wins. The shell rewrites the flag inside config.json."""
    data = _read_sidecar(config_file)
    if isinstance(data, dict) and "enable" in data:
        return bool(data["enable"])
    background = load_config(config_file).get("background") or {}
    return bool((background.get("multiMonitor") or {}).get("enable"))


def _write_sidecar(entries, enabled, config_file=None):
    side = assignments_path(config_file)
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({
        "enable": bool(enabled),
        "wallpapersByMonitor": entries,
    }, indent=2) + "\n", encoding="utf-8")


def store_assignment(key, path, first, last, thumbnail="", config_file=None):
    entries = upsert(load_entries(config_file), key, path, first, last, thumbnail)
    _write_sidecar(entries, True, config_file)
    return entries


def set_multi_enabled(enabled, config_file=None):
    _write_sidecar(load_entries(config_file), enabled, config_file)


def effective_from_files(config_file=None, map_file=None):
    config = load_config(config_file)
    background = config.get("background") or {}
    multi = background.get("multiMonitor") or {}
    mapping = load_mapping(map_file)
    enabled = multi_enabled(config_file)
    if not _read_sidecar(config_file):
        enabled = bool(multi.get("enable"))
    return effective(
        load_entries(config_file),
        mapping,
        list(mapping),
        background.get("wallpaperPath") or "",
        enabled,
    )


def main(argv):
    if len(argv) >= 2 and argv[1] == "key" and len(argv) >= 3:
        print(assignment_key(argv[2], load_mapping()))
        return 0
    if len(argv) >= 2 and argv[1] == "effective":
        print(json.dumps(effective_from_files()))
        return 0
    if len(argv) >= 2 and argv[1] == "set" and len(argv) >= 6:
        store_assignment(argv[2], argv[3], argv[4], argv[5], argv[6] if len(argv) >= 7 else "")
        return 0
    if len(argv) >= 3 and argv[1] == "enable":
        set_multi_enabled(argv[2] not in ("0", "false", "off"))
        return 0
    print("usage: wallpaper_identity.py key MONITOR | effective | set KEY PATH FIRST LAST [THUMB]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
