#!/usr/bin/env bash
# Create or update the "dev" build container on the Steam Frame (Fedora 44 toolbox,
# aarch64, via distrobox). Safe to re-run: it only creates what's missing and dnf
# skips installed packages. This package list is the source of truth for rebuilding
# the container.
# Usage: setup/dev-container.sh   (on the Frame, or from a PC over SSH)
# Needs distrobox in ~/.local/bin on the Frame (see the top-level README).
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
. "$root/scripts/_env.sh"

packages=(
  # toolchains
  gcc gcc-c++ clang clang-devel cmake meson ninja-build make pkgconf-pkg-config cargo rust git
  # libraries for Frametop's native pieces
  pipewire-devel libxkbcommon-devel libinput-devel systemd-devel dbus-devel libdrm-devel
  mesa-libgbm-devel wayland-devel vulkan-loader-devel vulkan-headers plasma-wayland-protocols wlroots-devel
  # ft_pointer SteamVR driver: static C++ runtime (the host has an older glibc)
  libstdc++-static
  # hand tracking (deferred: not installed by install.sh; hands/run.sh install builds it): ft-hands
  # reads the calibration with jsoncpp; ft-camd runs on the host, linked statically. Its Python
  # tools (hands/tools) need NumPy and OpenCV, which aren't here: Fedora's python3-opencv pulls
  # in over a gigabyte (hands/README.md says how to get them)
  jsoncpp-devel glibc-static
  # hand recorder (hands/rec): its export compresses recordings with zstd; its Upload page and
  # hub.py upload to Hugging Face with huggingface_hub (also the hf command, for hf auth login)
  zstd python3-huggingface-hub
  # Frametop Input Settings app (Kirigami, PySide6)
  python3-pyside6 kf6-kirigami kf6-qqc2-desktop-style qt6-qtwayland breeze-icon-theme plasma-breeze
  # Frametop remote desktop (VNC bridge through krdp)
  krdp freerdp tigervnc-x11-server xrandr
  # remote displays (stream/): moonlight-common-c and moonlight-embedded's libgamestream,
  # and the host's sound (Opus, played through PipeWire's PulseAudio server)
  openssl-devel libcurl-devel expat-devel libuuid-devel json-devel opus-devel pulseaudio-libs-devel
  # diagnostics and remote UI testing
  wayland-utils xorg-x11-server-Xvfb ImageMagick xdotool
  # Experimental Hyprland session. These stay in the container: Dolphin and
  # Firefox are the file manager and browser the controller chords launch,
  # and the icon themes give Quickshell a fallback icon. The shell's named
  # fonts are staged beside the config, not installed on the host.
  dolphin firefox kitty fish foot pavucontrol eza btop tesseract tesseract-langpack-eng wf-recorder fuzzel hicolor-icon-theme breeze-icon-theme
  google-noto-sans-fonts google-noto-sans-mono-fonts wl-clipboard
  # end-4 tools. These are clients and generators, not host services:
  # jq and the image tools run the wallpaper and color scripts, cliphist
  # stores the session clipboard, qalc is the launcher calculator, and
  # grim/slurp take a panel shot. NetworkManager, BlueZ, and UPower are
  # not installed here; the container cannot attach to SteamOS's system bus.
  jq qalculate playerctl grim slurp libnotify cliphist python3-pillow
  cava swappy translate-shell wtype
  pango-devel cairo-devel libjpeg-turbo-devel mpv-devel hyprland-protocols-devel
  libsoup3-devel glib2-devel gettext-devel alsa-lib-devel
  xdg-user-dirs ffmpeg-free iw
  # end-4's "Choose file" wallpaper button runs kdialog. The thumbnail
  # plugins are what turn that list into pictures. Upscayl is not packaged
  # for this ARM64 container; ImageMagick scales the image instead.
  # matugen recolors the session from the wallpaper. numpy, pillow, and
  # opencv are the container's own builds; materialyoucolor is installed
  # into the session virtualenv, not copied from the laptop.
  kdialog kio-extras kdegraphics-thumbnailers ffmpegthumbs
  matugen python3-numpy python3-opencv python3-pip python3-devel
)

on_frame_script "$FRAME_REPO" "${packages[@]}" <<'EOF'
set -euo pipefail
repo=$1
shift
distrobox=$HOME/.local/bin/distrobox
[ -x "$distrobox" ] || { echo "distrobox not found at $distrobox (see the top-level README)" >&2; exit 1; }
if ! podman container exists dev; then
  echo "creating the dev container (Fedora 44 toolbox)"
  "$distrobox" create --yes --name dev --image registry.fedoraproject.org/fedora-toolbox:44
fi
"$repo/scripts/container-up.sh" dev  # in a scope of its own, not this shell's
"$distrobox" enter dev -- bash -c '
set -euo pipefail
echo "installing ${#@} packages (already-installed ones are skipped)"
sudo -n dnf install -y -q "$@" 2>&1 | { grep -vE "is already installed|^Nothing to do|^$" || true; }
# OpenVR programs built here (the pointer helper and probe) look for the runtime at /opt/steamvr.
[ -e /opt/steamvr ] || sudo -n ln -s /run/host/opt/steamvr /opt/steamvr
echo "dev container ready: $(. /etc/os-release; echo $PRETTY_NAME), glibc $(ldd --version | head -1 | grep -oE "[0-9.]+$")"
' dev "$@"
EOF
