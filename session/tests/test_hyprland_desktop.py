"""Install layout for the pinned Hyprland desktop. No headset and no systemd."""
import os
import stat
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "session" / "install-hyprland-desktop.sh"


def _touch(path: Path, exe: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n" if exe else "")
    if exe:
        path.chmod(path.stat().st_mode | stat.S_IEXEC)


class HyprlandDesktopInstallTests(unittest.TestCase):
    def _source(self, root: Path) -> None:
        session = root / "session"
        session.mkdir(parents=True)
        for name in (
            "frametop-desktop.sh",
            "deckard-nested-desktop.desktop",
            "plasma-desktop.desktop",
        ):
            (session / name).write_text((ROOT / "session" / name).read_text())
        _touch(root / "screens/build/ft-screens", exe=True)
        _touch(root / "build/aquamarine/lib64/libaquamarine.so.14")
        _touch(root / "build/end4/bin/starship", exe=True)
        _touch(root / "build/end4/lib64/libhyprlang.so.2")
        _touch(root / "stage/config/quickshell/ii/shell.qml")
        _touch(root / "stage/theme/fonts/MaterialSymbolsRounded.ttf")
        _touch(root / "input/input-relay.py")
        _touch(root / "scripts/in-box", exe=True)
        _touch(root / "scripts/container-up.sh", exe=True)
        _touch(root / "layout/ft-layout", exe=True)
        _touch(root / "layout/ft_layout.py")
        _touch(root / "layout/ft-hide-show", exe=True)
        _touch(root / "layout/ft-layout-reset", exe=True)
        _touch(root / "display-settings/ft-display-settings", exe=True)
        _touch(root / "input-settings/ft-input-settings", exe=True)
        _touch(root / "remote-displays/ft-remote-displays", exe=True)
        _touch(root / "steam/steamui.py")
        _touch(root / "gaze/probe/ft-gazeprobe", exe=True)
        _touch(root / "display-settings/ft-screens-toggle.desktop")
        _touch(root / "display-settings/ft-layout-reset.desktop")

    def test_offline_install_pins_a_release_and_keeps_plasma_separate(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "src"
            home = root / "home"
            self._source(source)
            plasma = home / "frametop-api/session/frametop-session.sh"
            _touch(plasma, exe=True)
            env = dict(os.environ)
            env.update({
                "HOME": str(home),
                "FT_INSTALL_HOME": str(home),
                "FT_INSTALL_SOURCE": str(source),
                "FT_INSTALL_OFFLINE": "1",
                "FT_PLASMA_SESSION": str(plasma),
            })
            result = subprocess.run(
                ["bash", str(INSTALL)], env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            pin = home / ".local/share/frametop/hyprland-desktop"
            current = (pin / "current").resolve()
            self.assertTrue((current / "screens/build/ft-screens").is_file())
            for path in ("display-settings/ft-display-settings", "input-settings/ft-input-settings",
                         "remote-displays/ft-remote-displays", "steam/steamui.py", "gaze/probe/ft-gazeprobe"):
                self.assertTrue((current / path).is_file(), path)
            self.assertTrue((current / "build/end4/bin/starship").is_file())
            self.assertTrue((current / "build/end4/lib64/libhyprlang.so.2").is_file())
            self.assertIn("commit=unversioned", (current / "VERSION").read_text())
            self.assertTrue((pin / "config/quickshell/ii/shell.qml").is_file())
            self.assertTrue((pin / "theme/fonts/MaterialSymbolsRounded.ttf").is_file())
            self.assertTrue((current / "stage/theme/fonts/MaterialSymbolsRounded.ttf").is_file())
            desktop = (home / ".local/share/applications/deckard-nested-desktop.desktop").read_text()
            self.assertIn(f"Exec={home}/.local/bin/frametop-desktop", desktop)
            self.assertIn("X-Steam-Special=Desktop", desktop)
            plasma_entry = (home / ".local/share/applications/frametop-plasma-desktop.desktop").read_text()
            self.assertIn("Name=Plasma Desktop", plasma_entry)
            self.assertNotIn("X-Steam-Special", plasma_entry)
            self.assertEqual((home / ".config/frametop/desktop-selection").read_text().strip(), "hyprland")
            restore = (pin / "rollback/latest/restore.sh").read_text()
            self.assertNotIn("fdstore", restore)
            self.assertTrue(plasma.is_file())
            refused = subprocess.run(
                ["bash", str(INSTALL)],
                env={**env, "FT_INSTALL_SOURCE": str(home / "frametop-api"), "FT_INSTALL_HOME": str(home)},
                capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("frametop-api", refused.stderr)

    def test_stop_scripts_do_not_kill_every_ft_screens(self):
        for name in (
            "frametop-session.sh",
            "plasma-stop.sh",
            "desktop-stop.sh",
            "hyprland-stop.sh",
            "desktops.sh",
            "install-hyprland-desktop.sh",
        ):
            text = (ROOT / name).read_text() if name == "desktops.sh" else (ROOT / "session" / name).read_text()
            self.assertNotIn("pkill -x ft-screens", text, name)
            self.assertNotIn("clean --what=fdstore", text, name)


if __name__ == "__main__":
    unittest.main()
