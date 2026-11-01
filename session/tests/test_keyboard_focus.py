"""Keybind routing follows the panel under the laser."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "input"))
import desktop_route  # noqa: E402


class KeyboardFocusTests(unittest.TestCase):
    def test_named_panel_keeps_the_keyboard_from_the_unnamed_claim(self):
        state = desktop_route.keyboard_claim({}, ["keyboard", "hyprland", "ft_hypr_exp"], 10)
        self.assertEqual(state["control"], "ft_hypr_exp")
        held = desktop_route.keyboard_claim(state, ["keyboard", "hyprland"], 11)
        self.assertEqual(held["control"], "ft_hypr_exp")
        self.assertEqual(held["until"], state["until"])

    def test_leaving_the_panel_clears_only_that_claim(self):
        state = desktop_route.keyboard_claim({}, ["keyboard", "hyprland"], 10)
        state = desktop_route.keyboard_claim(state, ["keyboard", "hyprland", "ft_hypr_exp"], 11)
        self.assertEqual(state["control"], "ft_hypr_exp")
        cleared = desktop_route.keyboard_claim(state, ["keyboard", "hyprland", "0", "ft_hypr_exp"], 12)
        self.assertEqual(cleared["control"], "")
        self.assertGreater(cleared["until"], 12)

    def test_the_center_desktop_releasing_does_not_drop_the_panel(self):
        state = desktop_route.keyboard_claim({}, ["keyboard", "hyprland", "ft_hypr_exp"], 10)
        held = desktop_route.keyboard_claim(state, ["keyboard", "hyprland", "0"], 11)
        self.assertEqual(held["control"], "ft_hypr_exp")

    def test_unnamed_claim_uses_the_default_route(self):
        state = desktop_route.keyboard_claim({}, ["keyboard", "hyprland"], 10)
        self.assertEqual(state["control"], "")
        self.assertGreater(state["until"], 10)

    def test_a_bad_socket_name_is_not_a_claim(self):
        state = desktop_route.keyboard_claim({}, ["keyboard", "hyprland", "../ft"], 10)
        self.assertEqual(state["control"], "")


if __name__ == "__main__":
    unittest.main()
