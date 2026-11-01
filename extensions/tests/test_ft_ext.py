"""Offline contract tests for the extension client with a fake abstract UNIX socket."""
import secrets
import socket
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft_ext import ExtensionError, Frametop, live_control  # noqa: E402


class ExtensionClientTest(unittest.TestCase):
    def setUp(self):
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.name = "ft-ext-test-" + secrets.token_hex(6)
        self.server.bind("\0" + self.name)
        self.server.settimeout(1)

    def tearDown(self):
        self.server.close()

    def exchange(self, expected: str, reply: str, invoke):
        received = []
        def service():
            data, address = self.server.recvfrom(4096)
            received.append(data.decode())
            self.server.sendto(reply.encode(), address)
        thread = threading.Thread(target=service)
        thread.start()
        try:
            result = invoke(Frametop(self.name))
            self.assertEqual(received, [expected])
            return result
        finally:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    def test_discovery(self):
        self.assertEqual(self.exchange("ext api", "ok 1", lambda c: c.api_version()), 1)
        self.assertEqual(self.exchange("ext caps", "ok screen.status screen.opacity",
                                       lambda c: c.capabilities()),
                         {"screen.status", "screen.opacity"})

    def test_status(self):
        self.assertEqual(self.exchange(
            "ext status 2", "ok opacity 0.4000 target 0.5000 fading 1 moving 0 pinned none",
            lambda c: c.screen_status(2)),
            {"opacity": "0.4000", "target": "0.5000", "fading": "1",
             "moving": "0", "pinned": "none"})

    def test_control_commands(self):
        self.exchange("ext opacity 1 0.250000 450", "ok",
                      lambda c: c.opacity(1, .25, 450))
        self.exchange("ext move 1 1.000000 2.000000 -3.000000 0.000000 0.000000 0.000000 450",
                      "ok", lambda c: c.move(1, 1, 2, -3, 0, 0, 0, 450))

    def test_rejection(self):
        with self.assertRaises(ExtensionError):
            self.exchange("ext status 1", "error no desktop screen 1",
                          lambda c: c.screen_status(1))

    def test_invalid_input_is_never_sent(self):
        c = Frametop(self.name)
        for fn in (lambda: c.opacity(1, -0.1), lambda: c.opacity(1, float("nan")),
                   lambda: c.opacity(0, .5), lambda: c.opacity(1, .5, -1),
                   lambda: c.move(1, 0, 0, float("inf"), 0, 0, 0),
                   lambda: c.request("ext api\nbad")):
            with self.assertRaises(ValueError):
                fn()

    def test_live_control_keeps_an_explicit_socket(self):
        self.assertEqual(live_control("ft-ext-test"), "ft-ext-test")

    def test_non_compositor_timeout(self):
        with self.assertRaises(ExtensionError):
            Frametop("ft-ext-missing-" + secrets.token_hex(6), timeout=.05).api_version()


if __name__ == "__main__":
    unittest.main()
