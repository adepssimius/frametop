# end-4 on the Steam Frame

The experimental session runs the laptop's end-4 Quickshell config from a
staged copy. This file is the dependency inventory and the Frame-specific
choices. The laptop files under `~/.config` are not edited. Packages are
added in `setup/dev-container.sh` and installed only inside the Fedora
`dev` container.

Quickshell in that container is 0.2.1 (`dacfa9de`). The laptop shell is
written for 0.3.2 (`4f508be`). The first live test's broken look was the
missing theme, which is now staged. One 0.2.1 difference is still visible:
Qt's native text path drops some Material Symbol ligatures, so the staged
icon widget uses Qt's own renderer while `FT_FRAME_SESSION` is set. Building
0.3.2 is not required for the rest of the shell.

## Desktop tools

| Need | Used for | Frame |
| --- | --- | --- |
| `jq` | Wallpaper, color, and settings scripts | Install in the container |
| `curl` | Konachan and other downloads | Already in the container |
| ImageMagick, `ffmpeg-free` | Wallpaper probes and video wallpapers | ImageMagick was already installed; `ffmpeg-free` is added |
| `python3-pillow` | Image helpers under `scripts/` | Install in the container |
| `qalc` (`qalculate`) | Calculator in the launcher | Install in the container |
| `cliphist`, `wl-paste` | Clipboard history | Install `cliphist`. Startup stores one blank entry (`cliphist list` exits 1 on an empty database) and then runs `wl-paste --watch cliphist store` on this session's Wayland socket |
| `grim`, `slurp` | Region screenshots | Install in the container |
| `libnotify` | `notify-send` from scripts | Install in the container. The shell is the notification server on the session bus |
| `playerctl` | A few media fallbacks | Install in the container. Playback itself is MPRIS on the session bus |
| `xdg-user-dirs` | Wallpaper download directory | Install in the container |
| `iw` | SSID for the network status shim | Install in the container |

The Konachan and osu wallpaper scripts on the laptop read
`~/.config/illogical-impulse/config.json`. The staged copies use
`$XDG_CONFIG_HOME`, which the session sets to the staged config. They do
not read or write the host config. A download that returns no image is
dropped, and the current wallpaper stays.

`kdialog` is the "Choose file" button. It opens on the Hyprland panel
with `QT_QPA_PLATFORMTHEME=kde` and the session config home, where the
file dialog is set to the thumbnail view (`View Style=8`, preview on).
`kio-extras` and `kdegraphics-thumbnailers` supply the image plugins.
Upscayl is an x86_64 Arch application, so it is not installed. An image
smaller than the panel is scaled to the panel with ImageMagick before it
is applied. There is no Upscayl prompt.

## Theme

`session/frame-theme.sh` seeds colors, the wallpaper path, and fontconfig
for the staged shell. `session/frame-kde-theme.py` writes a KDE color
scheme and GTK icon settings into `~/.config/frametop/hyprland` and
`~/.local/share/frametop/hyprland`. `session/bin/dolphin` is ahead of
`/usr/bin` on the session `PATH` and points Dolphin at those directories
with `QT_QPA_PLATFORMTHEME=kde`. The nested session also selects the KDE
platform theme for apps launched directly from desktop entries, including
Frametop settings. Host Plasma keeps `~/.config`.

The terminal is Kitty, as in the laptop's shell actions. The container
includes Kitty and Fish; `session/kitty.conf` and `session/fish/config.fish`
seed the session's config once, and end-4 generates its wallpaper-derived
terminal colors. The Fish config uses `eza` for `ls` and initializes Starship
when available. `session/fish/starship.toml` mirrors the laptop prompt settings,
and `session/build-end4-tools.sh` supplies a pinned aarch64 Starship binary. `foot` remains
a fallback if Kitty is unavailable.

The container also includes `btop` (task-manager fallback), `tesseract` with
English data (OCR), `wf-recorder` (recording), and `fuzzel` (launcher fallback).
The upstream dependency inventory also names `cava`, `swappy`,
`translate-shell`, and `wtype`; the container includes those too. Their
installation alone does not validate the corresponding shell actions.
The pinned tools build also compiles `hyprpicker` and `mpvpaper` from source.
`hyprsunset` and the SongRec CLI are also built from pinned sources;
Hyprsunset uses a private Hyprlang and protocol build to avoid changing the
container's Hyprland libraries. The isolated no-VR test found the color-transform protocol, but a second
night-filter client reported an existing manager and its control socket did
not answer. The shell integration and visual effect still need verification. The session-local `ydotool` key adapter sends end-4's keyboard events to
Frametop without a host daemon; it still needs headset validation.
Kitty's search kitten is seeded with the session configuration. Network,
Bluetooth, Polkit, portal-dependent screen capture, and the other intentionally
changed services below still need separate session-level verification.

A wallpaper change runs `matugen` from the container (Fedora's 3.1.0 build;
it accepts the same templates and scheme names as the laptop's 4.2.0).
The shell also passes `--source-color-index`, which this build rejects, so
the session drops that flag before generating colors.
`session/frame-wallpaper.sh` writes a config whose outputs are the session
state `colors.json` and GTK css under `~/.config/frametop/hyprland`. It
does not use the laptop's `~/.config/matugen/config.toml`, because those
paths are the host config, and it does not run the laptop's pywalfox or
sddm hooks. Quickshell watches that `colors.json` and repaints.

`frame-kde-theme.py` then writes `FrametopEnd4.colors` and `kdeglobals`
into the session directories Dolphin already uses, including the active color
groups in `kdeglobals`. Existing unrelated KDE settings are preserved. `ColorSchemeHash` is
the SHA1 of the scheme file, which is what KDE compares when a running
app decides to reload. The color virtualenv lives at
`~/.local/share/frametop/hyprland/color-venv`. It is created in the
container with `materialyoucolor` 2.0.10 and the container's Pillow,
NumPy, and OpenCV. It is not a copy of the laptop venv.
`kde-material-you-colors` is not run: that program writes
`~/.config/kdeglobals` and asks Plasma's KWin to reconfigure.

## Audio

The session's `XDG_RUNTIME_DIR` is a private `/tmp/ftH.*` directory so
Hyprland's socket fits in `sun_path`. PipeWire clients would otherwise look
there and miss SteamOS. When `/run/user/<uid>/pipewire-0` exists, the
session sets `PIPEWIRE_RUNTIME_DIR` to that directory. When the Pulse
socket exists, it sets `PULSE_SERVER`. No second PipeWire is started.
The volume widget talks to the headset's existing server.

## Network, Bluetooth, power, brightness

The container can see `/run/host/run/dbus/system_bus_socket`, but a client
there fails with `Failed to get credentials`. A proxy socket hung instead
of connecting. NetworkManager, BlueZ, and UPower are therefore not usable
from the container, and their daemons are not installed beside SteamOS.

`session/bin/nmcli` is on the session `PATH` only. It answers the status
commands end-4 already runs, using the container's default route (distrobox
shares the host network namespace). `nmcli radio`, `connection`, and
`device wifi connect` exit with an error and do not change the headset
radio. The bar can show the link. Wifi scanning and radio toggles stay
inoperative on purpose.

Battery and Bluetooth widgets already hide themselves when UPower and BlueZ
are absent. Brightness and `ddcutil` have no panel backlight to drive. The
staged brightness service returns immediately when `FT_FRAME_SESSION` is
set, so those controls do not spawn missing programs. Suspend, hyprlock,
and hypridle stay out of the session launcher.

## Intentionally different

| Laptop piece | Frame |
| --- | --- |
| ChatGPT bridge at `/home/tovakai/Projects/quickshell-chatgpt` | Not started. The staged copy sets `onlineAllowed: false`, and the command exits without the laptop venv. The venv is not copied |
| Conflict killer (`killall kded6`) | Returns before doing anything when `FT_FRAME_SESSION` is set |
| Monitor brightness, DDC, suspend | No-ops or hidden |
| Host Plasma session bus | Not imported. The nested session has its own bus |
| `kde-material-you-colors` and the laptop color virtualenv | Not used. `matugen` and a session virtualenv write the frametop theme directories |

## Controller

R1 is a left click. R3 is a right click. Trigger+R3 closes the focused
window once and should not also right-click. The press/release rules are
in `input/test/controller-chords-test.py`. This has not been confirmed in
the headset.

## Checks

Offline: `python3 -m unittest session.tests.test_stage_end4 session.tests.test_frame_desktop session.tests.test_frame_services` and `input/test/controller-chords-test.py`.

On the Frame, after `setup/dev-container.sh`: the new commands resolve
inside `dev`, and a `--no-vr` smoke must leave `kded6` running. Do not
restart the input relay or open a headset session until that is approved.

Frametop settings entries in the nested launcher resolve to the same release
as the running Hyprland session. Input Settings lists profiles from the
Hyprland layout there; Plasma keeps its own profiles and launchers.
