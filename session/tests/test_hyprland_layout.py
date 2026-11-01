"""Hyprland screen identity, poses, and the Plasma layout staying untouched."""
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.sys.path.insert(0, str(ROOT / "session"))
import hyprland_layout as layout  # noqa: E402
import hyprland_outputs as outputs  # noqa: E402


def two():
    data = layout.default_layout()
    layout.add_screen(data)
    return data


def three():
    data = two()
    layout.add_screen(data)
    return data


class HyprlandLayoutTests(unittest.TestCase):
    def test_default_is_the_current_primary_panel(self):
        data = layout.default_layout()
        self.assertEqual(data["screens"], [{
            "id": "hypr-1", "slot": 1, "size": [1920, 1080], "metres": 1.5, "scale": 1.0, "curve": 0.0,
        }])
        self.assertEqual(layout.shell_export(data).splitlines()[:2], ["count=1", "outputs=1"])
        self.assertIn("1920x1080@1.500", layout.shell_export(data))

    def test_two_and_three_screens_do_not_overlap(self):
        for count, builder in ((2, two), (3, three)):
            data = builder()
            data["mode"] = "preset"
            poses = layout.poses_for(data)
            self.assertEqual(len(poses), count)
            xs = [round(p["pos"][0], 3) for p in poses]
            self.assertEqual(len(set(xs)), count, xs)
            self.assertTrue(all(p["pos"][2] < 0 for p in poses))
            # Neighbours are separated by about a panel width, not stacked.
            ordered = sorted(xs)
            self.assertGreater(ordered[1] - ordered[0], 0.5)

    def test_assignment_ignores_arrival_order_and_reuses_a_freed_slot(self):
        data = three()
        first = layout.assign_monitors(data, ["WAYLAND-2", "WAYLAND-3", "WAYLAND-1"], {})
        slots = {name: slot for name, slot, _ident in first["claims"]}
        self.assertEqual(slots, {"WAYLAND-1": 1, "WAYLAND-2": 2, "WAYLAND-3": 3})

        # Same map, list reversed: nothing moves.
        again = layout.assign_monitors(data, ["WAYLAND-3", "WAYLAND-1", "WAYLAND-2"], first["mapping"])
        self.assertEqual(again["mapping"], first["mapping"])
        self.assertEqual(again["released"], [])

        # WAYLAND-2 dies and comes back as WAYLAND-9. Slot 2 is the one that
        # comes back. Slots 1 and 3 keep their monitors and their ids.
        hypr2 = next(s for s in data["screens"] if s["slot"] == 2)
        hypr2["pos"] = [0.4, 0.0, -2.0]
        live = ["WAYLAND-1", "WAYLAND-9", "WAYLAND-3"]
        rebound = layout.assign_monitors(data, live, first["mapping"])
        by_slot = {slot: name for name, slot, _ident in rebound["claims"]}
        self.assertEqual(by_slot[1], "WAYLAND-1")
        self.assertEqual(by_slot[2], "WAYLAND-9")
        self.assertEqual(by_slot[3], "WAYLAND-3")
        self.assertEqual(next(s["pos"] for s in data["screens"] if s["slot"] == 2), [0.4, 0.0, -2.0])

    def test_removing_one_screen_keeps_the_others(self):
        data = three()
        for screen, pos in zip(data["screens"], ([-1.2, 0, -2], [0, 0, -2], [1.2, 0, -2])):
            screen["pos"] = list(pos)
        removed = layout.remove_screen(data, 2)
        self.assertEqual(removed["id"], "hypr-2")
        self.assertEqual([(s["id"], s["slot"], s["pos"]) for s in data["screens"]], [
            ("hypr-1", 1, [-1.2, 0, -2]),
            ("hypr-3", 3, [1.2, 0, -2]),
        ])
        # The gap stays a gap. The next screen reuses slot 2 and gets a new id.
        layout.add_screen(data)
        added = next(s for s in data["screens"] if s["slot"] == 2)
        self.assertEqual(added["id"], "hypr-4")
        self.assertNotIn("pos", added)
        self.assertEqual(next(s["pos"] for s in data["screens"] if s["id"] == "hypr-3"), [1.2, 0, -2])

    def test_hide_show_uses_the_hyprland_compositor(self):
        os.sys.path.insert(0, str(ROOT / "layout"))
        import ft_layout
        original = ft_layout.hyprland_desktop_up
        ft_layout.hyprland_desktop_up = lambda: True
        self.addCleanup(lambda: setattr(ft_layout, "hyprland_desktop_up", original))
        os.environ.pop("FT_CONTROL_SOCKET", None)
        self.assertEqual(ft_layout.screens_control_addr(), b"\0ft_hyprland")
        ft_layout.hyprland_desktop_up = lambda: False
        self.assertEqual(ft_layout.screens_control_addr(), b"\0ft_screens")

    def test_reset_places_screens_from_the_hyprland_layout(self):
        data = two()
        asked = []
        def ask(text):
            asked.append(text)
            if text == "head":
                return "ok 0 0 0 0"
            return "ok"
        layout.cli_reset(ask=ask)
        self.assertTrue(any(item.startswith("place 1") for item in asked))
        self.assertTrue(any(item.startswith("visibility ") for item in asked))

    def test_settings_do_not_list_hyprland_exceptions(self):
        self.assertEqual(layout.LIMITATIONS, ())
        data = two()
        layout.set_count(data, 3)
        self.assertEqual([screen["slot"] for screen in layout.screens_by_slot(data)], [1, 2, 3])
        layout.set_count(data, 1)
        self.assertEqual(len(layout.screens_by_slot(data)), 1)

    def test_a_profile_remembers_which_screen_a_window_was_on(self):
        data = two()
        clients = [{
            "class": "firefox", "title": "Docs", "monitor": 1, "pid": 1,
            "workspace": {"id": 2, "name": "2"}, "floating": False,
            "at": [10, 20], "size": [800, 600], "cmd": ["firefox"],
        }, {
            "class": "quickshell", "title": "bar", "monitor": 0,
            "workspace": {"id": 1}, "at": [0, 0], "size": [1, 1],
        }]
        monitors = [{"id": 0, "name": "WAYLAND-1"}, {"id": 1, "name": "WAYLAND-2"}]
        mapping = {"WAYLAND-1": "hypr-1", "WAYLAND-2": "hypr-2"}
        layout.save_profile(data, "Work", clients, monitors, mapping)
        rows = layout.profile_window_rows(data, "Work")
        self.assertEqual(rows, [{"app": "firefox", "where": "screen 2, workspace 2"}])
        self.assertEqual(layout.profile_record(data, "Work")["windows"][0]["cmd"], ["firefox"])
        evals = layout.open_profile_evals(data, "Work", mapping, [{
            "class": "firefox", "address": "0xabc",
        }])
        self.assertEqual(len(evals), 1)
        self.assertIn('monitor = "WAYLAND-2"', evals[0])
        self.assertIn("0xabc", evals[0])

    def test_poll_places_a_screen_once_and_does_not_create_startup_outputs_twice(self):
        data = two()
        state = {"mapping": {}, "placed": [], "rules": {}}
        first = outputs.step(["WAYLAND-1"], state, data, baseline=2)
        kinds = [cmd[0] for cmd in first["commands"]]
        self.assertLess(kinds.index("slot"), kinds.index("claim"))
        self.assertIn(("claim", "claim WAYLAND-1 1"), first["commands"])
        self.assertEqual(first["create"], 0)
        self.assertEqual(first["place_ids"], ["hypr-1"])
        state = first["state"]
        state["placed"] = list(first["place_ids"])
        second = outputs.step(["WAYLAND-1", "WAYLAND-2"], state, data, baseline=2)
        self.assertEqual(second["place_ids"], ["hypr-2"])
        self.assertNotIn("hypr-1", second["place_ids"])
        self.assertEqual(second["create"], 0)
        state = second["state"]
        state["placed"] = list(state.get("placed") or []) + second["place_ids"]
        third = outputs.step(["WAYLAND-2", "WAYLAND-1"], state, data, baseline=2)
        self.assertEqual(third["place_ids"], [])
        self.assertTrue(all(cmd[0] != "monitor" or False for cmd in third["commands"] if cmd[0] == "monitor") or True)
        # The monitor rule was already recorded, so the pointer row is not rewritten.
        self.assertFalse(any(cmd[0] == "monitor" for cmd in third["commands"]))
        self.assertFalse(any(cmd[0] == "slot" for cmd in third["commands"]))

    def test_slot_is_sent_before_claim_and_failures_are_reported(self):
        from unittest.mock import patch
        commands = [("slot", "slot 2 1920 1080 1.500"), ("claim", "claim WAYLAND-2 2")]
        with patch.object(outputs, "send_control", return_value=True) as send:
            outputs.apply_commands(commands)
            self.assertEqual([call.args[0] for call in send.call_args_list], [arg for _, arg in commands])
        with patch.object(outputs, "send_control", return_value=False) as send:
            with self.assertRaises(RuntimeError):
                outputs.apply_commands(commands)
            self.assertEqual(send.call_count, 1)

    def test_adding_a_screen_creates_one_output_and_a_removed_monitor_is_dropped(self):
        data = two()
        state = {"mapping": {"WAYLAND-1": "hypr-1", "WAYLAND-2": "hypr-2"}, "placed": ["hypr-1", "hypr-2"], "rules": {}}
        layout.add_screen(data)
        added = outputs.step(["WAYLAND-1", "WAYLAND-2"], state, data, baseline=2)
        self.assertEqual(added["create"], 1)
        self.assertIn(("create", "wayland"), added["commands"])
        layout.remove_screen(data, 3)
        # The third monitor has no slot once the screen is gone.
        state = added["state"]
        state["mapping"] = added["actions"]["mapping"]
        dropped = outputs.step(["WAYLAND-1", "WAYLAND-2", "WAYLAND-4"], state, data, baseline=3)
        self.assertIn("WAYLAND-4", dropped["remove"])
        self.assertNotIn("WAYLAND-1", dropped["remove"])
        self.assertNotIn("WAYLAND-2", dropped["remove"])

    def test_monitor_row_edges_touch_in_slot_order(self):
        data = three()
        mapping = {"WAYLAND-1": "hypr-1", "WAYLAND-2": "hypr-2", "WAYLAND-3": "hypr-3"}
        rules = layout.monitor_commands(data, mapping)
        self.assertEqual([rule["x"] for rule in rules], [0, 1920, 3840])
        self.assertIn('output="WAYLAND-2", mode="1920x1080@60", position="1920x0", scale=1', rules[1]["eval"])

    def test_saved_pose_restores_for_its_id_relative_to_the_heading(self):
        data = two()
        data["mode"] = "custom"
        data["screens"][1]["pos"] = [1.0, 0.0, -2.0]
        data["screens"][1]["face"] = [20.0, 0.0]
        data["screens"][1]["roll"] = 0
        data["screens"][0]["pos"] = [-1.0, 0.0, -2.0]
        data["screens"][0]["face"] = [-20.0, 0.0]
        data["screens"][0]["roll"] = 0
        commands = layout.place_commands(data, eye=(0.0, 1.6, 0.0), heading=90.0)
        by_slot = {cmd["slot"]: cmd["place"] for cmd in commands}
        self.assertIn("place 2", by_slot[2])
        # Heading is added to the saved face, so this is not a room-fixed yaw.
        self.assertIn("110.000", by_slot[2])

    def test_write_does_not_touch_the_plasma_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            plasma = home / ".config" / "frametop-layout.json"
            plasma.parent.mkdir(parents=True)
            plasma.write_text('{"screens": [{"size": [3440, 1440]}]}\n')
            hypr = home / ".config" / "frametop" / "hyprland-layout.json"
            env_home = os.environ.get("HOME")
            os.environ["HOME"] = str(home)
            os.environ["FT_HYPRLAND_LAYOUT"] = str(hypr)
            try:
                data = layout.load()
                layout.add_screen(data)
                layout.save(data)
                self.assertEqual(plasma.read_text(), '{"screens": [{"size": [3440, 1440]}]}\n')
                saved = json.loads(hypr.read_text())
                self.assertEqual([s["id"] for s in saved["screens"]], ["hypr-1", "hypr-2"])
                self.assertNotIn("frametop-layout.json", hypr.read_text())
            finally:
                if env_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = env_home
                os.environ.pop("FT_HYPRLAND_LAYOUT", None)

    def test_named_layout_restores_one_screen_without_moving_the_other(self):
        data = two()
        data["screens"][0]["pos"] = [-1, 0, -2]
        data["screens"][1]["pos"] = [1, 0, -2]
        layout.save_named(data, "Wide")
        data["screens"][1]["pos"] = [3, 0, -2]
        data["screens"][0]["metres"] = 2.0
        layout.use_named(data, "Wide")
        self.assertEqual(data["screens"][1]["pos"], [1, 0, -2])
        self.assertEqual(data["screens"][0]["metres"], 1.5)
        self.assertEqual(data["mode"], "custom")

    def test_alongside_names_do_not_replace_the_installed_socket(self):
        self.assertEqual(layout.socket_name(), "ft-hyprland-0")
        self.assertEqual(layout.control_name(), "ft_hyprland")
        os.environ["FT_HYPRLAND_SOCKET"] = "ft-hypr-exp-0"
        os.environ["FT_HYPRLAND_CONTROL"] = "ft_hypr_exp"
        self.addCleanup(os.environ.pop, "FT_HYPRLAND_SOCKET", None)
        self.addCleanup(os.environ.pop, "FT_HYPRLAND_CONTROL", None)
        self.assertEqual(layout.socket_name(), "ft-hypr-exp-0")
        self.assertEqual(layout.control_name(), "ft_hypr_exp")

    def test_load_keeps_profiles_visibility_hosts_and_pins(self):
        with tempfile.TemporaryDirectory() as temp:
            hypr = Path(temp) / "hyprland-layout.json"
            os.environ["FT_HYPRLAND_LAYOUT"] = str(hypr)
            self.addCleanup(os.environ.pop, "FT_HYPRLAND_LAYOUT", None)
            data = two()
            data["visibility"] = {"mode": "toggle", "wrist_angle": 45}
            data["profiles"] = {"Work": {"hidden": [2], "windows": []}}
            data["default_profile"] = "Work"
            data["hosts"] = [{"name": "pc", "address": "10.0.0.2", "displays": []}]
            data["screens"][0]["pin"] = {"hand": "head", "rel": [0] * 12}
            layout.save(data)
            loaded = layout.load()
            self.assertEqual(loaded["visibility"]["mode"], "toggle")
            self.assertEqual(loaded["profiles"]["Work"]["hidden"], [2])
            self.assertEqual(loaded["default_profile"], "Work")
            self.assertEqual(loaded["hosts"][0]["name"], "pc")
            self.assertEqual(loaded["screens"][0]["pin"]["hand"], "head")

    def test_every_plasma_layout_command_is_handled_on_hyprland(self):
        self.assertEqual(set(layout.LAYOUT_COMMANDS), {
            "apply", "reset", "capture", "save", "use", "start", "open", "default",
            "layouts", "rename", "delete", "launchers", "plan", "scale", "screen-args",
            "remote-view", "toggle", "hide", "show", "hidden", "pin", "unpin", "remote",
        })
        os.sys.path.insert(0, str(ROOT / "layout"))
        import ft_layout
        asked = []

        def ask(text):
            asked.append(text)
            if text == "head":
                return "ok 0 1.6 0 0"
            if text.startswith("get "):
                return "ok 0 1.6 -2  1 0 0  0 1 0  0 0 1  1.5 0.84 0 none"
            return "ok"

        class Sock:
            def ask(self, text, timeout=10.0):
                return ask(text)

        original_sock = ft_layout.screens_socket
        original_open = layout.open_windows
        ft_layout.screens_socket = lambda: Sock()
        layout.open_windows = lambda name: None
        self.addCleanup(lambda: setattr(ft_layout, "screens_socket", original_sock))
        self.addCleanup(lambda: setattr(layout, "open_windows", original_open))
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            hypr = home / "hyprland-layout.json"
            env_home = os.environ.get("HOME")
            os.environ["HOME"] = str(home)
            os.environ["FT_HYPRLAND_LAYOUT"] = str(hypr)
            try:
                data = two()
                for screen, pos in zip(data["screens"], ([-1, 0, -2], [1, 0, -2])):
                    screen["pos"] = list(pos)
                    screen["face"] = [0, 0]
                    screen["roll"] = 0
                layout.save(data)
                for argv in (
                    ["ft-layout", "toggle"],
                    ["ft-layout", "reset"],
                    ["ft-layout", "apply"],
                    ["ft-layout", "capture"],
                    ["ft-layout", "hide", "2"],
                    ["ft-layout", "show", "2"],
                    ["ft-layout", "hidden"],
                    ["ft-layout", "pin", "1", "head"],
                    ["ft-layout", "unpin", "1"],
                    ["ft-layout", "plan"],
                    ["ft-layout", "scale"],
                    ["ft-layout", "screen-args"],
                    ["ft-layout", "remote-view"],
                    ["ft-layout", "layouts"],
                    ["ft-layout", "launchers"],
                    ["ft-layout", "save", "Work"],
                    ["ft-layout", "use", "Work"],
                    ["ft-layout", "open", "Work"],
                    ["ft-layout", "default", "Work"],
                    ["ft-layout", "rename", "Work", "Desk"],
                    ["ft-layout", "delete", "Desk"],
                    ["ft-layout", "start"],
                    ["ft-layout", "remote", "list"],
                ):
                    asked.clear()
                    code = layout.cli(argv, ask=ask)
                    self.assertEqual(code, 0, argv)
                self.assertIsNone(layout.cli(["ft-layout", "not-a-command"], ask=ask))
                hidden = layout.load()
                self.assertNotIn("frametop-layout.json", hypr.read_text())
                self.assertTrue(any(s.get("pos") for s in hidden["screens"]))
            finally:
                if env_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = env_home
                os.environ.pop("FT_HYPRLAND_LAYOUT", None)

    def test_hide_writes_the_hyprland_layout_and_conceals_by_slot(self):
        os.sys.path.insert(0, str(ROOT / "layout"))
        import ft_layout
        asked = []

        class Sock:
            def ask(self, text, timeout=10.0):
                asked.append(text)
                return "ok"

        original = ft_layout.screens_socket
        ft_layout.screens_socket = lambda: Sock()
        self.addCleanup(lambda: setattr(ft_layout, "screens_socket", original))
        with tempfile.TemporaryDirectory() as temp:
            os.environ["FT_HYPRLAND_LAYOUT"] = str(Path(temp) / "hyprland-layout.json")
            self.addCleanup(os.environ.pop, "FT_HYPRLAND_LAYOUT", None)
            layout.save(two())
            layout.cli(["ft-layout", "hide", "2"], ask=lambda text: "ok")
            saved = layout.load()
            by_slot = {int(s["slot"]): s for s in saved["screens"]}
            self.assertTrue(by_slot[2].get("hidden"))
            self.assertFalse(by_slot[1].get("hidden"))
            self.assertEqual(asked, ["conceal 2"])

    def test_pointer_focus_follows_the_pointed_slot(self):
        mapping = {"WAYLAND-1": "hypr-1", "WAYLAND-2": "hypr-2"}
        expr, current = outputs.pointer_focus_eval(mapping, 2, "")
        self.assertEqual(expr, 'hl.dispatch(hl.dsp.focus({ monitor = "WAYLAND-2" }))')
        self.assertEqual(current, "WAYLAND-2")
        expr, current = outputs.pointer_focus_eval(mapping, 2, current)
        self.assertEqual(expr, "")
        expr, current = outputs.pointer_focus_eval(mapping, 1, current)
        self.assertIn("WAYLAND-1", expr)
        expr, current = outputs.pointer_focus_eval(mapping, 0, current)
        self.assertEqual(expr, "")
        data = two()
        data["screens"][1]["id"] = "hypr-9"
        expr, current = outputs.pointer_focus_eval({"WAYLAND-7": "hypr-9"}, 2, "", data)
        self.assertIn('WAYLAND-7', expr)


if __name__ == "__main__":
    unittest.main()
