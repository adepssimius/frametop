#!/usr/bin/env python3
"""Run desktop actions inside the container that already hosts Hyprland.

A controller press used to start a new container entry, which cost about a
third of a second before hyprctl ran. This process stays up with the session
and answers one action name per connection on
$XDG_RUNTIME_DIR/frametop-desktop.sock.
"""
import os
import socket
import subprocess
import sys

ACTIONS = (
    "workspace-prev",
    "workspace-next",
    "window-prev",
    "window-next",
    "close",
    "terminal",
    "files",
    "browser",
    "launcher",
)
SOCK_NAME = "frametop-desktop.sock"
UNREACHABLE = 111


def script_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "frame-desktop-action.sh")


def send(path, action, timeout=3.0):
    """Return the action's status, or UNREACHABLE when nothing is listening."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(path)
        sock.sendall((action + "\n").encode())
        data = b""
        while b"\n" not in data and len(data) < 32:
            chunk = sock.recv(32)
            if not chunk:
                break
            data += chunk
    except OSError:
        return UNREACHABLE
    finally:
        sock.close()
    code = data.split(b"\n", 1)[0]
    if code.isdigit():
        return int(code)
    return 1


def serve(path, script):
    directory = os.path.dirname(path)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    os.chmod(path, 0o600)
    server.listen(4)
    server.settimeout(2.0)
    while os.path.isdir(directory):
        try:
            conn, _addr = server.accept()
        except socket.timeout:
            continue
        except OSError:
            return
        with conn:
            data = b""
            while b"\n" not in data and len(data) < 64:
                chunk = conn.recv(64)
                if not chunk:
                    break
                data += chunk
            action = data.decode("utf-8", "replace").strip()
            if action == "ping":
                conn.sendall(b"0\n")
                continue
            if action not in ACTIONS:
                conn.sendall(b"2\n")
                continue
            env = dict(os.environ)
            env["FT_DESKTOP_INNER"] = "1"
            try:
                result = subprocess.run([script, action], env=env, check=False, timeout=2.5)
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
            try:
                conn.sendall(f"{code}\n".encode())
            except OSError:
                pass  # caller may have disconnected while the action ran


def main(argv):
    if len(argv) == 4 and argv[1] == "--send":
        raise SystemExit(send(argv[2], argv[3]))
    if len(argv) not in (2, 3):
        raise SystemExit(f"usage: {argv[0]} SOCKET [ACTION_SCRIPT] | {argv[0]} --send SOCKET ACTION")
    serve(argv[1], argv[2] if len(argv) == 3 else script_path())


if __name__ == "__main__":
    main(sys.argv)
