"""Per-monitor wallpaper keys follow the screen id, not WAYLAND-N."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

os.sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wallpaper_identity as wall  # noqa: E402
import hyprland_outputs as outputs  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "stage_end4", Path(__file__).resolve().parents[1] / "stage-end4.py")
stage_end4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stage_end4)


class WallpaperIdentityTests(unittest.TestCase):
    def test_two_monitors_keep_their_own_images(self):
        mapping = {"WAYLAND-1": "hypr-1", "WAYLAND-2": "hypr-2"}
        entries = [
            {"monitor": "hypr-1", "path": "/a.png", "workspaceFirst": 1, "workspaceLast": 10},
            {"monitor": "hypr-2", "path": "/b.png", "workspaceFirst": 1, "workspaceLast": 10},
        ]
        shown = wall.effective(entries, mapping, ["WAYLAND-1", "WAYLAND-2"], "/global.png", True)
        self.assertEqual(shown["WAYLAND-1"]["path"], "/a.png")
        self.assertEqual(shown["WAYLAND-2"]["path"], "/b.png")

    def test_three_monitors_and_a_recreated_output(self):
        entries = wall.upsert([], "hypr-1", "/a.png", 1, 10)
        entries = wall.upsert(entries, "hypr-2", "/b.png", 1, 5)
        entries = wall.upsert(entries, "hypr-3", "/c.png", 6, 10)
        mapping = {"WAYLAND-4": "hypr-2", "WAYLAND-1": "hypr-1", "WAYLAND-9": "hypr-3"}
        shown = wall.effective(entries, mapping, list(mapping), "/global.png", True)
        self.assertEqual(shown["WAYLAND-4"]["path"], "/b.png")
        self.assertEqual(shown["WAYLAND-9"]["workspaceFirst"], 6)
        self.assertNotEqual(shown["WAYLAND-1"]["path"], shown["WAYLAND-4"]["path"])

    def test_focused_change_does_not_replace_the_other_screen(self):
        entries = wall.upsert(
            [{"monitor": "hypr-1", "path": "/a.png"}], "hypr-2", "/b.png", 1, 10)
        self.assertEqual([entry["path"] for entry in entries if entry["monitor"] == "hypr-1"], ["/a.png"])
        self.assertEqual(wall.assignment_key("WAYLAND-2", {"WAYLAND-2": "hypr-2"}), "hypr-2")

    def test_global_mode_uses_one_image_and_keeps_the_assignments(self):
        entries = [{"monitor": "hypr-1", "path": "/a.png"}, {"monitor": "hypr-2", "path": "/b.png"}]
        mapping = {"WAYLAND-1": "hypr-1", "WAYLAND-2": "hypr-2"}
        shown = wall.effective(entries, mapping, ["WAYLAND-1", "WAYLAND-2"], "/global.png", False)
        self.assertEqual({item["path"] for item in shown.values()}, {"/global.png"})
        self.assertEqual(len(entries), 2)

    def test_reorder_follows_the_id(self):
        entries = [
            {"monitor": "hypr-1", "path": "/left.png"},
            {"monitor": "hypr-2", "path": "/right.png"},
        ]
        swapped = {"WAYLAND-2": "hypr-1", "WAYLAND-1": "hypr-2"}
        shown = wall.effective(entries, swapped, ["WAYLAND-1", "WAYLAND-2"], "", True)
        self.assertEqual(shown["WAYLAND-2"]["path"], "/left.png")
        self.assertEqual(shown["WAYLAND-1"]["path"], "/right.png")

    def test_sidecar_survives_an_empty_config_list(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            config.write_text(json.dumps({
                "background": {
                    "wallpaperPath": "/global.png",
                    "multiMonitor": {"enable": True},
                    "wallpapersByMonitor": [],
                }
            }), encoding="utf-8")
            wall.store_assignment("hypr-1", "/a.png", 1, 10, config_file=config)
            wall.store_assignment("hypr-2", "/b.png", 1, 10, config_file=config)
            mapping = root / "map.json"
            mapping.write_text(json.dumps({
                "mapping": {"WAYLAND-1": "hypr-1", "WAYLAND-2": "hypr-2"}
            }), encoding="utf-8")
            shown = wall.effective_from_files(config, mapping)
            self.assertEqual(shown["WAYLAND-1"]["path"], "/a.png")
            self.assertEqual(shown["WAYLAND-2"]["path"], "/b.png")
            self.assertEqual(shown["hypr-1"]["path"], "/a.png")
            rewritten = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(rewritten["background"]["wallpapersByMonitor"], [])

    def test_files_round_trip_the_effective_map(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            config.write_text(json.dumps({
                "background": {
                    "wallpaperPath": "/global.png",
                    "multiMonitor": {"enable": True},
                    "wallpapersByMonitor": [{"monitor": "hypr-1", "path": "/a.png"}],
                }
            }), encoding="utf-8")
            mapping = root / "map.json"
            mapping.write_text(json.dumps({"mapping": {"WAYLAND-8": "hypr-1"}}), encoding="utf-8")
            shown = wall.effective_from_files(config, mapping)
            self.assertEqual(shown["WAYLAND-8"]["path"], "/a.png")

    def test_a_missing_startup_output_is_created_after_three_polls(self):
        baseline, short = outputs.settle_baseline(2, 1, 2, 0)
        self.assertEqual((baseline, short), (2, 1))
        baseline, short = outputs.settle_baseline(baseline, 1, 2, short)
        baseline, short = outputs.settle_baseline(baseline, 1, 2, short)
        self.assertEqual(baseline, 1)
        self.assertEqual(short, 0)
        baseline, short = outputs.settle_baseline(baseline, 2, 2, short)
        self.assertEqual(baseline, 2)

    def test_stage_patches_add_per_monitor_wallpaper(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "config"
            script = root / "quickshell/ii/scripts/colors/switchwall.sh"
            script.parent.mkdir(parents=True)
            script.write_text(
                'set_wallpaper_path() {\n'
                '    local path="$1"\n'
                '    if [ -f "$SHELL_CONFIG_FILE" ]; then\n'
                '        jq --arg path "$path" \'.background.wallpaperPath = $path\' "$SHELL_CONFIG_FILE" > "$SHELL_CONFIG_FILE.tmp" && mv "$SHELL_CONFIG_FILE.tmp" "$SHELL_CONFIG_FILE"\n'
                '    fi\n'
                '}\n'
                'kill_existing_mpvpaper() {\n'
                '    pkill -f -9 mpvpaper || true\n'
                '}\n'
                '            --image)\n'
                '                imgpath="$2"\n'
                '                shift 2\n'
                '                ;;\n'
                '            --noswitch)\n'
                '                noswitch_flag="1"\n'
                '                imgpath=$(jq -r \'.background.wallpaperPath\' "$SHELL_CONFIG_FILE" 2>/dev/null || echo "")\n'
                '                shift\n'
                '                ;;\n',
                encoding="utf-8",
            )
            (root / "quickshell/ii/services").mkdir(parents=True)
            notes = stage_end4.apply_frame_patches(root)
            stage_end4.install_wallpaper_listener(root)
            text = script.read_text(encoding="utf-8")
            self.assertIn("frame_wallpaper_key", text)
            self.assertIn("wallpapersByMonitor", text)
            self.assertIn("--monitor", text)
            self.assertIn("kill_mpvpaper", text)
            self.assertTrue((root / "quickshell/ii/services/WallpaperListener.qml").is_file())
            self.assertTrue(any("switchwall.sh" in note for note in notes))
