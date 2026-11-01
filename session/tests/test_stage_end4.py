"""The end-4 stage copy stays out of ~/.config and skips secrets."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "stage_end4", Path(__file__).resolve().parents[1] / "stage-end4.py"
)
stage_end4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stage_end4)


class StageEnd4Tests(unittest.TestCase):
    def test_existing_shell_process_signals_are_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            colors = root / "quickshell/ii/scripts/colors"
            colors.mkdir(parents=True)
            wall = colors / "switchwall.sh"
            wall.write_text('pkill -f -9 mpvpaper\npkill -f -9 "mpvpaper .* ${monitor}( |$)"\n')
            terminal = colors / "applycolor.sh"
            terminal.write_text('kill -SIGUSR1 $(pidof kitty)\n')
            stage_end4.patch_session_processes(root)
            self.assertNotIn("pkill", wall.read_text())
            self.assertIn('frame-stop-mpvpaper.py" "$monitor"', wall.read_text())
            self.assertIn("frame-reload-kitty.py", terminal.read_text())
            before = (wall.read_text(), terminal.read_text())
            stage_end4.patch_session_processes(root)
            self.assertEqual(before, (wall.read_text(), terminal.read_text()))

    def test_copy_keeps_internal_links_and_skips_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hypr = root / "hypr"
            (hypr / "hyprland").mkdir(parents=True)
            (hypr / "hyprland.lua").write_text("hl = {}\n")
            (hypr / "backup-old.lua").write_text("nope\n")
            (hypr / "token.pem").write_text("secret\n")
            (hypr / "key.lua").write_text('local x = "BEGIN PRIVATE KEY"\n')
            icon = hypr / "hyprland" / "icon.svg"
            icon.write_text("<svg/>\n")
            link = hypr / "alias.svg"
            link.symlink_to("hyprland/icon.svg")
            outside = root / "outside.txt"
            outside.write_text("nope\n")
            (hypr / "escape.svg").symlink_to(outside)
            qs = root / "ii"
            (qs / ".chatgpt-integration").mkdir(parents=True)
            (qs / ".chatgpt-integration" / "manifest.json").write_text("{}\n")
            (qs / "shell.qml").write_text("import Quickshell\n")
            dest = root / "repo" / "stage" / "config"
            notes = stage_end4.stage(hypr, qs, dest, replace=False)
            self.assertTrue((dest / "hypr" / "hyprland.lua").is_file())
            self.assertTrue((dest / "hypr" / "alias.svg").is_symlink())
            self.assertEqual(os.readlink(dest / "hypr" / "alias.svg"), "hyprland/icon.svg")
            self.assertFalse((dest / "hypr" / "escape.svg").exists())
            self.assertFalse((dest / "hypr" / "backup-old.lua").exists())
            self.assertFalse((dest / "hypr" / "token.pem").exists())
            self.assertFalse((dest / "hypr" / "key.lua").exists())
            self.assertFalse((dest / "quickshell" / "ii" / ".chatgpt-integration").exists())
            self.assertTrue((dest / "quickshell" / "ii" / "shell.qml").is_file())
            self.assertTrue(any("secret" in note or "skip" in note for note in notes))
            with self.assertRaises(SystemExit):
                stage_end4.stage(hypr, qs, dest, replace=False)
            home_dest = Path.home() / ".config" / "hypr"
            self.assertTrue(stage_end4.user_config_blocked(home_dest))

    def test_stage_keeps_theme_files_and_patches_the_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hypr = root / "hypr"
            (hypr / "hyprland").mkdir(parents=True)
            (hypr / "hyprland.lua").write_text("hl = {}\n")
            qs = root / "ii"
            popup = qs / "modules" / "ii" / "notificationPopup" / "NotificationPopup.qml"
            popup.parent.mkdir(parents=True)
            popup.write_text("screen: Config.options.notifications.forceMonitor.enable\n")
            bar = qs / "modules" / "ii" / "bar" / "BarContent.qml"
            bar.parent.mkdir(parents=True)
            bar.write_text("padding: workspacesWidget.widgetPadding\n")
            killer = qs / "services" / "ConflictKiller.qml"
            killer.parent.mkdir(parents=True)
            killer.write_text("            if (Config.ready) checkConflictsProc.running = true\n")
            bright = qs / "services" / "Brightness.qml"
            bright.write_text(
                "    function increaseBrightness(): void {\n"
                "    function decreaseBrightness(): void {\n"
                "    onMonitorsChanged: {\n        ddcMonitors = [];\n"
            )
            symbol = qs / "modules" / "common" / "widgets" / "MaterialSymbol.qml"
            symbol.parent.mkdir(parents=True)
            symbol.write_text("import qs.modules.common\nimport QtQuick\n    renderType: Text.NativeRendering\n")
            chat = qs / "services" / "ai" / "ChatGptBridge.qml"
            chat.parent.mkdir(parents=True)
            chat.write_text(
                "import QtQuick\nimport Quickshell.Io\n    property bool onlineAllowed: true\n"
                "        command: [\"/home/tovakai/Projects/quickshell-chatgpt/.venv/bin/python\", \"-m\", \"bridge\", \"serve\"]\n"
                "        workingDirectory: \"/home/tovakai/Projects/quickshell-chatgpt\"\n"
            )
            for name in ("random_konachan_wall.sh", "random_osu_wall.sh"):
                script = qs / "scripts" / "colors" / "random" / name
                script.parent.mkdir(parents=True, exist_ok=True)
                script.write_text(
                    'illogicalImpulseConfigPath="$HOME/.config/illogical-impulse/config.json"\n'
                )
            (qs / "shell.qml").write_text("import Quickshell\n")
            impulse = root / "impulse"
            (impulse / "actions").mkdir(parents=True)
            (impulse / "config.json").write_text('{"background": {"wallpaperPath": "/laptop/wall.png"}}\n')
            (impulse / "installed_listfile").write_text("not copied\n")
            state = root / "state"
            colors = state / "user" / "generated"
            colors.mkdir(parents=True)
            (colors / "colors.json").write_text("{}\n")
            (state / "states.json").write_text("{}\n")
            wall = root / "wall.png"
            wall.write_text("png")
            font = root / "OneFont.ttf"
            font.write_text("font")
            dest = root / "repo" / "stage" / "config"
            stage_end4.stage(
                hypr, qs, dest, replace=False, impulse=impulse, theme_state=state,
                wallpaper=wall, font_files=[font],
            )
            self.assertIn("monitor.enable", popup_text(dest))
            self.assertIn("padding: 5", (dest / "quickshell/ii/modules/ii/bar/BarContent.qml").read_text())
            killer_text = (dest / "quickshell/ii/services/ConflictKiller.qml").read_text()
            self.assertIn("FT_FRAME_SESSION", killer_text)
            bright_text = (dest / "quickshell/ii/services/Brightness.qml").read_text()
            self.assertEqual(bright_text.count('if (Quickshell.env("FT_FRAME_SESSION")) return'), 3)
            symbol_text = (dest / "quickshell/ii/modules/common/widgets/MaterialSymbol.qml").read_text()
            self.assertIn("Text.QtRendering", symbol_text)
            self.assertIn("import Quickshell", symbol_text)
            chat_text = (dest / "quickshell/ii/services/ai/ChatGptBridge.qml").read_text()
            self.assertIn("property bool onlineAllowed: false", chat_text)
            self.assertIn('workingDirectory: "/tmp"', chat_text)
            self.assertIn('test -z \\"$FT_FRAME_SESSION\\"', chat_text)
            self.assertNotIn("/home/tovakai/Projects/quickshell-chatgpt/.venv/bin/python\", \"-m\"", chat_text)
            for name in ("random_konachan_wall.sh", "random_osu_wall.sh"):
                script_text = (dest / "quickshell/ii/scripts/colors/random" / name).read_text()
                self.assertIn("${XDG_CONFIG_HOME:-$HOME/.config}", script_text)
                self.assertNotIn('"$HOME/.config/illogical-impulse', script_text)
            self.assertTrue((dest / "illogical-impulse" / "config.json").is_file())
            self.assertFalse((dest / "illogical-impulse" / "installed_listfile").exists())
            theme = dest.parent / "theme"
            self.assertTrue((theme / "quickshell" / "user" / "generated" / "colors.json").is_file())
            self.assertTrue((theme / "wallpaper.png").is_file())
            self.assertTrue((theme / "fonts" / "OneFont.ttf").is_file())


def popup_text(dest: Path) -> str:
    return (dest / "quickshell/ii/modules/ii/notificationPopup/NotificationPopup.qml").read_text()


if __name__ == "__main__":
    unittest.main()
