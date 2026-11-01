#!/usr/bin/env python3
"""Forward desktop keys from the installed input relay to this compositor.

The relay addresses @ft_screens. The experimental session listens on its own
control name, so while Plasma's ft-screens is not running this process holds
@ft_screens and passes messages on. Plasma leftover layout commands that
would move or resize Hyprland panels are dropped. Everything else, including
gaze/extension queries that need a reply, is proxied.
"""
import socket
import sys

# Plasma's services still send to @ft_screens. While this process holds that
# name, those datagrams have to reach the Hyprland compositor. Hide/Show
# Screens, pause, pins, gaze get/remotes, and the pointer's click/up go
# through here. place/size and KWin float commands stay listed so a leftover
# Plasma ft-layout or ft-floatd cannot move Hyprland panels.
DENIED_PREFIXES = (
    b"place ", b"size ", b"float ", b"unfloat ", b"pose ", b"sub ",
    b"minimized ", b"carry ",
)
# compositor.c does not reply to these; waiting would stall every key.
NO_REPLY_PREFIXES = (b"key ", b"click ")


def allowed(data):
    return not data.startswith(DENIED_PREFIXES)


def wants_reply(data):
    return not data.startswith(NO_REPLY_PREFIXES)


def main(argv):
    target_name = argv[1] if len(argv) > 1 else "ft_hyprland"
    listen = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        listen.bind("\0ft_screens")
    except OSError as exc:
        print(f"frametop: @ft_screens is in use ({exc}); keyboard forwarder stayed off", file=sys.stderr)
        return 0
    out = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    out.bind("")
    target = b"\0" + target_name.encode()
    print(f"frametop: forwarding desktop keys @ft_screens -> @{target_name}", flush=True)
    while True:
        data, addr = listen.recvfrom(8192)
        if not allowed(data):
            continue
        try:
            out.sendto(data, target)
            if not wants_reply(data):
                continue
            out.settimeout(1.0)
            reply, _ = out.recvfrom(8192)
            listen.sendto(reply, addr)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
