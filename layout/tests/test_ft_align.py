"""The geometry of joining two panels, and which tags a display shows. Run from the repo: python3 -m unittest layout/tests/test_ft_align.py"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import ft_align  # noqa: E402

WIDTH = 0.7127


def panel(x, turn_deg):
    """A flat panel at x, 1 m ahead of the viewer at the origin, turned about the vertical toward them."""
    a = math.radians(turn_deg)
    return [math.cos(a), 0, math.sin(a), x,
            0, 1, 0, 0,
            -math.sin(a), 0, math.cos(a), -1.0]


def edge(m, radius, side):
    """A curved panel's edge (side +1 right, -1 left) and the surface's direction there."""
    a = side * WIDTH / (2 * radius)
    point, along = [], []
    for i in range(3):
        point.append(m[i * 4 + 3] + m[i * 4] * radius * math.sin(a) + m[i * 4 + 2] * radius * (1 - math.cos(a)))
        along.append(m[i * 4] * math.cos(a) + m[i * 4 + 2] * math.sin(a))
    return point, along


class Join(unittest.TestCase):
    def setUp(self):
        self.left, self.right = panel(-0.37, 9.5), panel(0.37, -9.5)

    def test_seam_closes_and_is_tangent(self):
        left, right, radius, _, _ = ft_align.join_panels(self.left, self.right, WIDTH)
        a, along_a = edge(left, radius, 1)
        b, along_b = edge(right, radius, -1)
        self.assertLess(math.dist(a, b), 1e-6)
        self.assertGreater(sum(x * y for x, y in zip(along_a, along_b)), 0.999999)

    def test_default_keeps_the_panels_turn(self):
        _, _, radius, turn, sag = ft_align.join_panels(self.left, self.right, WIDTH)
        self.assertAlmostEqual(turn, 19, places=3)
        self.assertAlmostEqual(radius, WIDTH / math.radians(19), places=3)
        self.assertAlmostEqual(sag, radius * (1 - math.cos(math.radians(9.5))), places=6)

    def test_takes_a_chosen_radius(self):
        _, _, radius, _, _ = ft_align.join_panels(self.left, self.right, WIDTH, 1.2)
        self.assertEqual(radius, 1.2)

    def test_refuses_panels_the_wrong_way_round(self):
        with self.assertRaises(ValueError):
            ft_align.join_panels(self.right, self.left, WIDTH)

    def test_parallel_panels_need_a_radius(self):
        flat = panel(-0.37, 0), panel(0.37, 0)
        with self.assertRaises(ValueError):
            ft_align.join_panels(*flat, WIDTH)
        ft_align.join_panels(*flat, WIDTH, 2.0)


class Tags(unittest.TestCase):
    def test_a_macs_instances_have_their_own_tags(self):
        self.assertEqual(ft_align.first_tag({}, 0), 0)
        self.assertEqual(ft_align.first_tag({"port": 48089}, 9), 4)
        self.assertEqual(ft_align.first_tag({"port": 48189}, 9), 8)

    def test_windows_monitors_have_their_own_tags(self):
        self.assertEqual(ft_align.windows_first_tag("\\\\.\\DISPLAY1"), 0)
        self.assertEqual(ft_align.windows_first_tag("\\\\.\\DISPLAY3"), 8)
        with self.assertRaises(RuntimeError):
            ft_align.windows_first_tag("nonsense")

    def test_windows_tags_come_from_the_monitor_list(self):
        monitors = [{"device_id": "{a}", "display_name": "\\\\.\\DISPLAY2"}, {"device_id": "{b}", "display_name": "\\\\.\\DISPLAY3"}]
        self.assertEqual(ft_align.windows_tags([(104, {"app": "display:{a}", "id": "x"}), (105, {"app": "display:{b}", "id": "y"})], monitors), {104: 4, 105: 8})

    def test_an_inactive_windows_monitor_says_so(self):
        with self.assertRaisesRegex(RuntimeError, "isn't active"):
            ft_align.windows_tags([(104, {"app": "display:{gone}", "label": "OMEN"})], [])

    def test_a_measured_size_is_used(self):
        d = {"size": [2560, 1440], "physical": {"width_m": 0.71, "height_m": 0.4}, "port": 48189}
        e = ft_align.spec_entry(103, d, 8)
        self.assertEqual((e["width_m"], e["height_m"], e["measure"], e["first_id"]), (0.71, 0.4, False, 8))

    def test_an_unmeasured_size_keeps_the_screens_shape(self):
        e = ft_align.spec_entry(101, {"size": [3024, 1964]}, 0)
        self.assertTrue(e["measure"])
        self.assertAlmostEqual(e["height_m"] / e["width_m"], 1964 / 3024)


class Choices(unittest.TestCase):
    def setUp(self):
        self.layout = {"hosts": [{"name": "m", "address": "1", "displays": [{"id": "a", "app": "Desktop"}, {"id": "b", "app": "Desktop"}, {"id": "c", "app": "Desktop", "off": True}]}]}

    def test_neighbours_can_join(self):
        self.assertEqual([(c["a"], c["b"], c["joined"]) for c in ft_align.join_choices(self.layout)], [("a", "b", False)])

    def test_a_join_can_be_set_and_cleared(self):
        ft_align.set_join(self.layout, "a", "b", True)
        self.assertTrue(ft_align.join_choices(self.layout)[0]["joined"])
        ft_align.set_join(self.layout, "a", "b", False)
        self.assertFalse(ft_align.join_choices(self.layout)[0]["joined"])

    def test_a_display_joins_only_once(self):
        ft_align.set_join(self.layout, "a", "b", True)
        ft_align.set_join(self.layout, "b", "c", True)
        self.assertEqual(self.layout["align_joins"], [["b", "c"]])


if __name__ == "__main__":
    unittest.main()
