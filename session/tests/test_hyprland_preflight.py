"""Offline preflight tests for the experimental Hyprland session.

They must never start SteamVR, a container, or a nested compositor.
"""

import os
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "session" / "frametop-session.sh"
HYPRLAND = ROOT / "session" / "frametop-hyprland.sh"


def run(script: Path, home: Path, **values: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["XDG_RUNTIME_DIR"] = str(home)
    env.update(values)
    return subprocess.run(
        ["bash", str(script)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )


class HyprlandPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def socket_path(self):
        sock_path = self.home / "ft-screens-0"
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(sock_path))
        self.addCleanup(sock.close)
        return sock_path

    def test_unknown_desktop_rejected_before_start(self):
        result = run(ENTRY, self.home, FT_DESKTOP_SESSION="bogus")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("unknown desktop session", result.stderr)

    def test_hyprland_rejects_gamescope_before_start(self):
        result = run(
            ENTRY, self.home, FT_DESKTOP_SESSION="hyprland", FT_BACKEND="gamescope"
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("requires BACKEND=screens", result.stderr)

    def test_hyprland_requires_ft_screens_socket(self):
        result = run(
            HYPRLAND, self.home, WAYLAND_DISPLAY=str(self.home / "does-not-exist")
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Wayland socket", result.stderr)

    def test_hyprland_rejects_invalid_screen_counts(self):
        sock_path = self.socket_path()
        for count in ("0", "-1", "nope", "25"):
            with self.subTest(count=count):
                result = run(
                    HYPRLAND, self.home, WAYLAND_DISPLAY=str(sock_path),
                    FT_SCREEN_COUNT=count
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("invalid FT_SCREEN_COUNT", result.stderr)

    def test_hyprland_requires_config_file(self):
        sock_path = self.socket_path()
        result = run(
            HYPRLAND, self.home, WAYLAND_DISPLAY=str(sock_path),
            FT_SCREEN_COUNT="1", FT_HYPRLAND_CONFIG=str(self.home / "missing.conf")
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("configuration not found", result.stderr)

    def test_minimal_config_uses_lua(self):
        config = (ROOT / "session" / "hyprland-minimal.lua").read_text()
        self.assertIn("hl.monitor(", config)
        self.assertIn('hl.on("hyprland.start"', config)
        self.assertIn("hl.bind(", config)
        launcher = HYPRLAND.read_text()
        self.assertIn("hyprland-frame.lua", launcher)
        frame = (ROOT / "session" / "hyprland-frame.lua").read_text()
        self.assertIn("hyprland.lua", frame)
        self.assertIn("FT_HYPRLAND_STARTUP", frame)
        self.assertIn("HYPRLAND_NO_SD_VARS=1", launcher)
        self.assertIn("HYPRLAND_NO_SD_TARGET=1", launcher)
        self.assertIn("mktemp -d", launcher)

    def test_output_startup_rejects_bad_count(self):
        script = ROOT / "session" / "hyprland-on-start.sh"
        result = run(script, self.home, FT_SCREEN_COUNT="0")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("invalid FT_SCREEN_COUNT", result.stderr)

    def test_output_startup_creates_only_extra_wayland_outputs(self):
        binpath = self.home / "bin"
        binpath.mkdir()
        log = self.home / "calls.log"
        hyprctl = binpath / "hyprctl"
        hyprctl.write_text('#!/bin/sh\necho "$*" >> "$FT_TEST_LOG"\n')
        hyprctl.chmod(0o755)
        foot = binpath / "foot"
        foot.write_text('#!/bin/sh\necho "terminal" >> "$FT_TEST_LOG"\n')
        foot.chmod(0o755)
        script = ROOT / "session" / "hyprland-on-start.sh"
        result = run(
            script, self.home, FT_SCREEN_COUNT="3",
            PATH=str(binpath) + os.pathsep + os.environ.get("PATH", ""),
            FT_TEST_LOG=str(log),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            log.read_text().splitlines(),
            ["output create wayland", "output create wayland", "terminal"],
        )

    def test_no_vr_smoke_preflight_rejects_bad_duration(self):
        script = ROOT / "session" / "hyprland-smoke.sh"
        result = run(script, self.home, FT_HYPRLAND_SMOKE_SECONDS="0")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("5..60", result.stderr)

    def test_no_vr_smoke_isolated_sockets(self):
        source = (ROOT / "session" / "hyprland-smoke.sh").read_text()
        self.assertIn("--no-vr", source)
        self.assertIn("ft-hypr-smoke-$", source)
        self.assertIn("ft_hypr_smoke_$", source)
        self.assertIn("HYPRLAND_NO_SD_TARGET=1", source)
        self.assertIn("timeout --signal=TERM", source)
        self.assertIn("frametop_prepend_aquamarine", source)
        self.assertIn("error in client communication", source)
        self.assertIn("FT_HYPR_CONTROL", source)
        self.assertIn('b"toplevels"', source)

    def test_aquamarine_configure_fix_is_pinned(self):
        patch = (ROOT / "session" / "patches" / "aquamarine-0.15.1-configure-ack.patch").read_text()
        self.assertIn("applyConfigure", patch)
        self.assertIn("sendAckConfigure", patch)
        self.assertIn("pendingSize", patch)
        build = (ROOT / "session" / "build-aquamarine.sh").read_text()
        self.assertIn("2f9de98c0bd1b7b1b09c576e390a2fef436449762fb334163c414f0c300296f2", build)
        self.assertIn("v0.15.1", build)
        launcher = (ROOT / "session" / "frametop-hyprland.sh").read_text()
        self.assertIn("frametop_prepend_aquamarine", launcher)
        self.assertIn('LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"', launcher)

    def test_hyprland_vr_is_one_panel_and_scoped(self):
        env = ROOT / "session" / "hyprland-env.sh"
        result = subprocess.run(
            ["bash", "-c", f"""
set -euo pipefail
. "{env}"
frametop_hyprland_prepare_screens
test "$FT_SCREEN_COUNT" = 1
test "$FT_HYPR_OUTPUTS" = 1
test "$FT_OUTPUT_NAMES" = 1
test "$FT_HYPRLAND_SCREEN" = "1920x1080@1.5"
frametop_cmdline_is_hyprland_screens \\
  "ft-screens --socket ft-hyprland-0 --control ft_hyprland --screen 1920x1080@1.5 --spares 0" \\
  ft-hyprland-0
if frametop_cmdline_is_hyprland_screens \\
  "ft-screens --socket ft-screens-0 --screen 3440x1440@2.4 --spares 8" \\
  ft-hyprland-0; then
  exit 3
fi
FT_SCREEN_COUNT=3
FT_HYPR_OUTPUTS=
frametop_hyprland_prepare_screens
test "$FT_SCREEN_COUNT" = 3
test "$FT_HYPR_OUTPUTS" = 3
set +e
FT_SCREEN_COUNT=0
frametop_hyprland_prepare_screens
status=$?
set -e
test "$status" = 2
"""],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("invalid FT_SCREEN_COUNT", result.stderr)
        session = (ROOT / "session" / "frametop-session.sh").read_text()
        hypr, plasma = session.split("# PLASMA_VR_LAUNCH", 1)
        hypr = hypr.split("# HYPRLAND_VR_LAUNCH", 1)[1]
        self.assertIn("frametop_hyprland_prepare_screens", hypr)
        self.assertIn("hyprland_layout.py", hypr)
        self.assertIn("FT_OUTPUT_NAMES", env.read_text())
        self.assertNotIn("qs -c ii", (ROOT / "session" / "hyprland-env.sh").read_text())
        self.assertIn("frametop_stop_hyprland_session", hypr)
        self.assertNotIn("saved layout is not used", hypr)
        self.assertIn("frametop.hyprx", hypr)
        self.assertNotIn('FT_OVERLAY_PREFIX="${FT_OVERLAY_PREFIX:-frametop.hypr}"', hypr)
        self.assertNotIn("screen-args", hypr)
        self.assertNotIn("pkill -x", hypr)
        self.assertIn("screen-args", plasma)
        self.assertIn("plasma-stop.sh", plasma)
        self.assertNotIn("pkill -x", plasma)
        stop = (ROOT / "session" / "hyprland-stop.sh").read_text()
        self.assertIn("frametop_stop_hyprland_session", stop)
        self.assertNotIn("pkill", stop)

    def test_hyprland_runtime_dir_fits_socket_path(self):
        import re
        assign = re.compile(r"(^|\s)(export\s+)?XDG_RUNTIME_DIR=")
        for name in ("hyprland-smoke.sh", "frametop-hyprland.sh"):
            text = (ROOT / "session" / name).read_text()
            self.assertIn("mktemp -d /tmp/ftH.XXXXXX", text, name)
            for line in text.splitlines():
                code = line.split("#", 1)[0]
                if assign.search(code) and "/run/user" in code:
                    self.fail(f"{name} assigns Hyprland's runtime under /run/user: {line.strip()}")

    def test_protocol_checker_accepts_matching_globals(self):
        script = ROOT / "session" / "hyprland-protocol-check.py"
        sample = "\n".join([
            "interface: 'wl_compositor', version: 6, name: 1",
            "interface: 'wl_seat', version: 9, name: 2",
            "interface: 'wl_shm', version: 1, name: 3",
            "interface: 'xdg_wm_base', version: 6, name: 4",
            "interface: 'zwp_linux_dmabuf_v1', version: 4, name: 5",
        ])
        result = subprocess.run(
            ["python3", str(script)], input=sample, text=True,
            capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_protocol_checker_rejects_old_xdg_wm_base(self):
        script = ROOT / "session" / "hyprland-protocol-check.py"
        sample = "\n".join([
            "interface: 'wl_compositor', version: 6, name: 1",
            "interface: 'wl_seat', version: 9, name: 2",
            "interface: 'wl_shm', version: 1, name: 3",
            "interface: 'xdg_wm_base', version: 3, name: 4",
            "interface: 'zwp_linux_dmabuf_v1', version: 4, name: 5",
        ])
        result = subprocess.run(
            ["python3", str(script)], input=sample, text=True,
            capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("TOO OLD xdg_wm_base", result.stderr)


if __name__ == "__main__":
    unittest.main()
