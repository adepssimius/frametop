"""Offline checks for Frame network status and the session KDE theme."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NMCLI = ROOT / "session" / "bin" / "nmcli"
THEME = ROOT / "session" / "frame-kde-theme.py"


def run_nmcli(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    merged.update(env)
    return subprocess.run(
        ["bash", str(NMCLI), *args],
        env=merged,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


class FrameServiceTests(unittest.TestCase):
    def test_wifi_status_comes_from_the_default_route(self):
        with tempfile.TemporaryDirectory() as temp:
            sysfs = Path(temp) / "sys" / "class" / "net" / "wlan0" / "wireless"
            sysfs.mkdir(parents=True)
            env = dict(
                FT_NET_ROUTE_LINE="default via 10.0.0.1 dev wlan0",
                FT_NET_SYS=str(Path(temp) / "sys" / "class" / "net"),
                FT_NET_SSID="Frame",
                FT_NET_SIGNAL="64",
            )
            status = run_nmcli("-t", "-f", "TYPE,STATE", "d", "status", **env)
            self.assertEqual(status.stdout, "wifi:connected\n", status.stderr)
            link = run_nmcli("-t", "-f", "CONNECTIVITY", "g", **env)
            self.assertEqual(link.stdout, "full\n")
            name = run_nmcli("-t", "-f", "NAME", "c", "show", "--active", **env)
            self.assertEqual(name.stdout, "Frame\n")
            listed = run_nmcli("-g", "ACTIVE,SIGNAL,FREQ,SSID,BSSID,SECURITY", "d", "w", **env)
            self.assertEqual(listed.stdout, "yes:64:2412:Frame::\n")

    def test_radio_changes_are_refused(self):
        result = run_nmcli("radio", "wifi", "off", FT_NET_ROUTE_LINE="")
        self.assertEqual(result.returncode, 1)
        self.assertIn("SteamOS", result.stderr)

    def test_no_route_is_disconnected(self):
        result = run_nmcli("-t", "-f", "TYPE,STATE", "d", "status", FT_NET_ROUTE_LINE="", FT_NET_IFACE="")
        self.assertEqual(result.stdout, "ethernet:disconnected\n")

    def test_theme_writer_stays_out_of_the_host_config(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("frame_kde_theme", THEME)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            colors = Path(temp) / "colors.json"
            colors.write_text('{"surface": "#112233", "on_surface": "#eeeeee", "primary": "#abcdef"}\n')
            config = Path(temp) / "config"
            data = Path(temp) / "data"
            config.mkdir()
            (config / "kdeglobals").write_text("[General]\nUserSetting=keep\n")
            module.write_theme(colors, config, data)
            scheme = (data / "color-schemes" / "FrametopEnd4.colors").read_text()
            self.assertIn("BackgroundNormal=17,34,51", scheme)
            kdeglobals = (config / "kdeglobals").read_text()
            self.assertIn("ColorScheme=FrametopEnd4", kdeglobals)
            self.assertIn("UserSetting=keep", kdeglobals)
            self.assertIn("[Colors:Window]\nBackgroundNormal=17,34,51", kdeglobals)
            self.assertIn("Show Preview=true", kdeglobals)
            self.assertIn("View Style=8", kdeglobals)
            self.assertRegex(kdeglobals, r"ColorSchemeHash=[0-9a-f]{40}")
            with self.assertRaises(SystemExit):
                module.write_theme(colors, Path.home() / ".config", data)


if __name__ == "__main__":
    unittest.main()
