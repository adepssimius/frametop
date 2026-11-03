"""The geometry of curving panels into one, and which tags a display shows. Run from the repo: python3 -m unittest layout/tests/test_ft_align.py"""
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


def edge(m, width, radius, side):
    """A curved panel's edge (side +1 right, -1 left) and the surface's direction there."""
    a = side * width / (2 * radius)
    point, along = [], []
    for i in range(3):
        point.append(m[i * 4 + 3] + m[i * 4] * radius * math.sin(a) + m[i * 4 + 2] * radius * (1 - math.cos(a)))
        along.append(m[i * 4] * math.cos(a) + m[i * 4 + 2] * math.sin(a))
    return point, along


class Curve(unittest.TestCase):
    def setUp(self):
        self.left, self.right = panel(-0.37, 9.5), panel(0.37, -9.5)

    def assert_seam(self, a, b, width_a, width_b, radius):
        pa, along_a = edge(a, width_a, radius, 1)
        pb, along_b = edge(b, width_b, radius, -1)
        self.assertLess(math.dist(pa, pb), 1e-6)
        self.assertGreater(sum(x * y for x, y in zip(along_a, along_b)), 0.999999)

    def test_two_panels_close_and_are_tangent(self):
        (left, right), radius, _ = ft_align.curve_group([self.left, self.right], [WIDTH, WIDTH])
        self.assert_seam(left, right, WIDTH, WIDTH, radius)

    def test_default_keeps_the_panels_turn(self):
        _, radius, turn = ft_align.curve_group([self.left, self.right], [WIDTH, WIDTH])
        self.assertAlmostEqual(radius, WIDTH / math.radians(19), places=3)
        self.assertAlmostEqual(turn, 38, places=3)

    def test_takes_a_chosen_radius(self):
        _, radius, _ = ft_align.curve_group([self.left, self.right], [WIDTH, WIDTH], 1.2)
        self.assertEqual(radius, 1.2)

    def test_three_panels_of_different_widths_in_any_order(self):
        given = [panel(0.75, -20), panel(-0.65, 20), panel(0, 0)]    # right, left, middle
        widths = [0.6, 0.71, 0.5]
        (right, left, middle), radius, _ = ft_align.curve_group(given, widths)
        self.assert_seam(left, middle, 0.71, 0.5, radius)
        self.assert_seam(middle, right, 0.5, 0.6, radius)
        self.assertLess(left[3], middle[3])
        self.assertLess(middle[3], right[3])

    def test_stays_on_the_monitors(self):
        # Three real monitors edge to edge, the outer two turned 19 degrees in, so they come forward too.
        a = math.radians(19)
        off, forward = WIDTH / 2 * (1 + math.cos(a)), WIDTH / 2 * math.sin(a)
        left, right = panel(-off, 19), panel(off, -19)
        left[11] += forward
        right[11] += forward
        given = [left, panel(0, 0), right]
        placed, _, _ = ft_align.curve_group(given, [WIDTH] * 3)
        for real, curved in zip(given, placed):
            self.assertLess(math.dist([real[3], real[7], real[11]], [curved[3], curved[7], curved[11]]), 0.03)

    def test_refuses_panels_facing_away(self):
        with self.assertRaises(ValueError):
            ft_align.curve_group([panel(-0.37, -9.5), panel(0.37, 9.5)], [WIDTH, WIDTH])

    def test_parallel_panels_need_a_radius(self):
        flat = [panel(-0.37, 0), panel(0.37, 0)]
        with self.assertRaises(ValueError):
            ft_align.curve_group(flat, [WIDTH, WIDTH])
        ft_align.curve_group(flat, [WIDTH, WIDTH], 2.0)


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


class Locking(unittest.TestCase):
    good = {"shown_mm": 3, "spots": 40, "width_m": 0.71}

    def test_locks_after_staying_good(self):
        a = ft_align.AutoLock(False)
        self.assertFalse(a.update(self.good, 10))
        self.assertFalse(a.update(self.good, 12.9))
        self.assertTrue(a.update(self.good, 13))

    def test_a_dip_doesnt_count(self):
        a = ft_align.AutoLock(False)
        a.update(self.good, 10)
        a.update(dict(self.good, shown_mm=9), 11)
        self.assertFalse(a.update(self.good, 13.5))
        self.assertTrue(a.update(self.good, 16.5))

    def test_a_still_head_never_locks(self):
        a = ft_align.AutoLock(False)
        for t in range(20):
            self.assertFalse(a.update(dict(self.good, spots=1), t))

    def test_no_fit_never_locks(self):
        a = ft_align.AutoLock(False)
        for t in range(20):
            self.assertFalse(a.update({}, t))

    def test_measuring_waits_for_more_places(self):
        a = ft_align.AutoLock(True)
        for t in range(20):
            self.assertFalse(a.update(dict(self.good, spots=20), t))

    def test_measuring_waits_for_the_width_to_settle(self):
        a = ft_align.AutoLock(True)
        a.update(self.good, 10)
        self.assertFalse(a.update(dict(self.good, width_m=0.70), 13))   # moved 10 mm: starts over
        a.update(dict(self.good, width_m=0.70), 13.1)
        self.assertTrue(a.update(dict(self.good, width_m=0.7005), 16.2))


class HudLine(unittest.TestCase):
    def test_a_good_figure(self):
        self.assertEqual(ft_align.hud_line(102, {"shown_mm": 3.2}), "hud 102 1 About 3 mm|Position is good")

    def test_says_what_would_help(self):
        line = ft_align.hud_line(103, {"shown_mm": 40, "range_mm": [500, 20, 0], "distance_m": 0.6})
        self.assertEqual(line, "hud 103 0 About 40 mm|Move up and down")


class Choices(unittest.TestCase):
    def setUp(self):
        self.layout = {"hosts": [{"name": "m", "address": "1", "displays": [{"id": "a", "app": "Desktop"}, {"id": "b", "app": "Desktop"}, {"id": "c", "app": "Desktop", "off": True}]}]}

    def test_lists_a_computers_connected_displays(self):
        [choice] = ft_align.group_choices(self.layout)
        self.assertEqual(choice["groups"], 1)
        self.assertEqual([(d["id"], d["group"]) for d in choice["displays"]], [("a", 0), ("b", 0)])

    def test_a_group_can_be_set_and_cleared(self):
        ft_align.set_group(self.layout, "b", 1)
        self.assertEqual(ft_align.group_choices(self.layout)[0]["displays"][1]["group"], 1)
        ft_align.set_group(self.layout, "b", 0)
        self.assertEqual(ft_align.group_choices(self.layout)[0]["displays"][1]["group"], 0)

    def test_an_unknown_display_is_an_error(self):
        with self.assertRaises(RuntimeError):
            ft_align.set_group(self.layout, "nope", 1)

    def test_one_display_has_nothing_to_group_with(self):
        self.layout["hosts"][0]["displays"][1]["off"] = True
        self.assertEqual(ft_align.group_choices(self.layout), [])


if __name__ == "__main__":
    unittest.main()
