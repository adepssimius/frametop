"""Hyprland input-method focus and end-4 keyboard command handling."""
import importlib.machinery
import importlib.util
import socket
import struct
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


ime = load('hypr_textinput', ROOT / 'input/ft-hypr-textinput')
ydotool = load('frame_ydotool', ROOT / 'session/bin/ydotool')


def message(obj, opcode, payload=b''):
    return struct.pack('=II', obj, ((8 + len(payload)) << 16) | opcode) + payload


def global_event(number, name):
    return message(ime.REGISTRY, 0, struct.pack('=I', number) + ime.string(name) + struct.pack('=I', 1))


class HyprKeyboardTests(unittest.TestCase):
    def test_committed_focus_only_and_disconnect_release(self):
        client, server = socket.socketpair()
        server.settimeout(2)
        reports = []
        text_input = ime.TextInput(client, reports.append)
        worker = threading.Thread(target=text_input.run)
        worker.start()
        try:
            initial = b''
            while len(initial) < 24:
                initial += server.recv(1024)
            server.sendall(global_event(12, 'zwp_input_method_manager_v2') + global_event(13, 'wl_seat'))
            incoming = b''
            got_method = False
            while not got_method:
                incoming += server.recv(1024)
                while len(incoming) >= 8:
                    obj, word = struct.unpack_from('=II', incoming)
                    size = word >> 16
                    if len(incoming) < size:
                        break
                    incoming = incoming[size:]
                    if obj == text_input.manager:
                        got_method = True
            self.assertEqual((text_input.manager, text_input.seat, text_input.method), (4, 5, 6))
            server.sendall(message(text_input.method, 0) + message(text_input.method, 5))
            server.sendall(message(text_input.method, 1) + message(text_input.method, 5))
            server.sendall(message(text_input.method, 0) + message(text_input.method, 5))
        finally:
            server.close()
            worker.join(2)
            client.close()
        self.assertFalse(worker.is_alive())
        self.assertEqual(reports, [True, False, True, False])

    def test_ydotool_key_syntax_and_rejection(self):
        self.assertEqual(ydotool.parse(['key', '--key-delay', '0', '42:1', '30:1', '30:0', '42:0']),
                         [(42, 1), (30, 1), (30, 0), (42, 0)])
        self.assertEqual(len(ydotool.parse(['key', '-d', '1'] + [f'{x}:0' for x in range(249)])), 249)
        for invalid in (['type', 'abc'], ['key', '30:2'], ['key', '999:1'], ['key', '-d']):
            with self.assertRaises(ValueError):
                ydotool.parse(invalid)


if __name__ == '__main__':
    unittest.main()
