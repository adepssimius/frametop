# Hyprland desktop

SteamVR's **Desktop** entry launches this Hyprland session with the staged
end-4 shell. Plasma stays available as a separate **Plasma Desktop** entry
and is not started beside it.

The installed tree is pinned at
`~/.local/share/frametop/hyprland-desktop/current` (a symlink to
`releases/<commit>`). Wallpaper, colors, and the end-4 config live outside
that tree, in `~/.local/share/frametop/hyprland-desktop/config`,
`~/.config/frametop/hyprland`, and `~/.local/state/frametop/hyprland`, so a
later pin does not wipe them. The icon fonts live beside that config, in
`~/.local/share/frametop/hyprland-desktop/theme/fonts`. `~/frametop-api` is
not modified. It is the Plasma recovery tree.

```text
~/.local/bin/frametop-desktop status
~/.local/bin/frametop-desktop use hyprland
~/.local/bin/frametop-desktop use plasma
~/.local/bin/frametop-desktop rollback
```

`use plasma` and `rollback` start the `frametop-api` session. Neither clears
the input relay's file-descriptor store. Rollback restores the desktop
entry, input rules, layout file, and relay drop-in saved at install time.

Install from a tested checkout on the Frame (it must already contain
`screens/build/ft-screens`, `build/aquamarine`, and `stage/config`):

```text
session/build-end4-tools.sh
session/install-hyprland-desktop.sh --activate
```

The default panel is one 1920×1080 surface, 1.5 m wide, on sockets
`ft-hyprland-0` and `ft_hyprland`. More panels come from the Hyprland
layout file, described below. Quickshell is a client: if it fails to start
or exits, Hyprland keeps running. The Fedora `dev` container is started by
`scripts/in-box` when the compositor launches.

## Multiscreen

Each Hyprland monitor is one Frametop panel. Aquamarine titles the Wayland
window `aquamarine - WAYLAND-N`. That N is a creation counter, so ft-screens
does not use it as the slot and does not use whichever window appeared
first. `FT_OUTPUT_NAMES=1` parks the window until `claim WAYLAND-N <slot>`
names the slot. The session's output helper keeps the map: a monitor that
is still there keeps its slot, and a monitor that comes back under a new
name takes the slot that was freed. Slots are stable ids (`hypr-1`,
`hypr-2`, ...) in `~/.config/frametop/hyprland-layout.json`. Removing one
screen does not renumber the others or clear their saved poses.

The default file is still one 1920×1080 panel, 1.5 m wide. Extra screens
are added with `session/hyprland_layout.py add`. Their first pose is the
compositor's row in front of the headset. Arrange (Display Settings, or
`place` on the `ft_hyprland` socket) lays them out with the same geometry
as a Plasma preset. A poll does not send `place` again, so dragging a
panel in VR is not pulled back. A saved pose is restored relative to the
headset heading at restore time. It is not a fixed point in the room.

Hyprland's own monitor row is left to right with the edges touching, so
the pointer can cross. That row is separate from the VR pose. Workspace
keys stay the ones in the end-4 config. A controller click focuses the
monitor whose panel was hit.

Wallpapers follow the same ids. end-4 pull 2245 (Sevilze, GPL-3.0-or-later)
is the per-monitor picker: each monitor can have its own image, or one
image can stay on every monitor. The Frame copy stores the assignment
under `hypr-N` in `wallpapers-by-monitor.json` next to the shell config,
not under `WAYLAND-N` and not in the shell config itself. The shell
rewrites that config when other settings change, and that rewrite drops
a list kept inside it. The shell resolves `hypr-N` through the output
map when it draws. The last chosen image still recolors the one shared
Material You palette. A video wallpaper plays on the monitor it was
assigned to; its still thumbnail is stored on that assignment. The
installed config is not where this is edited. `session/stage-end4.py`
applies it to the staged shell.

Display Settings launched from the shell edits this session's
`hyprland-layout.json` and talks to its `ft_hyprland` socket. The desktop
file still starts the installed app, which only knows the Plasma layout;
the launcher switches to this checkout while `ft-hyprland-0` is the
running desktop.

Checking out this branch does not change the installed pin. The Hyprland
session reads `~/.config/frametop/hyprland-layout.json`, so the next
desktop launch opens the screens saved there. `FT_HYPRLAND_ALONGSIDE=1` is the separate
socket (`ft-hypr-exp-0`, control `ft_hypr_exp`, overlay `frametop.hyprx`)
for a session that has to leave the installed desktop running.

## Not supported on this desktop

These stay Plasma-only because they are KWin programs, not compositor
settings:
- KWin floating windows, the float decoration, and Launch as Standalone.
- The VNC / remote-desktop bridge (`desktops.sh remote`).

Hide/Show Screens, Reset Screen Layout, visibility, profiles, and the
SteamVR overlay keys (`frametop.screen.N`) are the same as Plasma.

Controller chords (Trigger as modifier, Trigger+R3 closes the focused
window) bind only while this session's route file is live and the desktop
is focused. They drop for SteamVR, a game, pause, or when Plasma's
`ft-screens-0` compositor is the one running.

Checking out the branch does not by itself change the Steam launcher. The
installer above does.

## Architecture

```text
SteamVR
  └── ft-screens (VR surfaces, pointer/keyboard relay, DMA-BUF)
        └── Hyprland (nested Wayland backend, one output surface per panel)
              └── Quickshell (end-4) and the controller action daemon
```

The Steam Desktop entry runs `~/.local/bin/frametop-desktop`, which reads
`~/.config/frametop/desktop-selection`. That file is `hyprland` or `plasma`.
It is not `DESKTOP=` in `~/.config/frametop.conf`. Only the `screens`
backend is supported and `FLOAT_SLOTS` becomes 0. KWin-specific layout
startup, floating windows, and remote desktop are bypassed. The Hyprland
input-method-v2 focus bridge requests Frametop's VR keyboard; it still needs
headset validation.

## Hardware bring-up stages

1. Work in `feature/hyprland-session` **without overwriting the currently
   installed Frametop checkout**. Build that branch's `screens/build.sh` in
   Frametop's existing Fedora development container; it advertises
   `xdg_wm_base` v6 rather than v3.
2. Run `session/hyprland-doctor.sh` to check what's installed in the
   container. It may start a stopped dev container, but installs nothing.
3. Install matching **aarch64** Hyprland (target 0.56.2, Aquamarine 0.15.1),
   `dbus-run-session` and optionally `foot` **inside that dev container**.
   Fedora 44 has no official Hyprland binary. COPR `sdegler/hyprland` (a
   clone of solopasha's packaging, no homepage) publishes Fedora 44 aarch64
   RPMs: Hyprland 0.56.2-2 built from tag `v0.56.2` and Aquamarine 0.15.1-1.
   Install them with a one-shot `--repofrompath` and
   `--setopt=install_weak_deps=False`. Do not `dnf copr enable` it: a
   persistent repo would pull Hyprland into later container upgrades, and
   the weak dependencies `uwsm` and `xdg-desktop-portal-hyprland` run
   `systemd-update-helper` for user units. Hyprland itself has no scriptlet.
   Do not change the SteamOS host root.
   That Aquamarine 0.15.1 still commits a buffer from `xdg_toplevel.configure`
   before `ack_configure`, which wlroots rejects (`xdg_surface has never been
   configured`). `session/build-aquamarine.sh` builds tag `v0.15.1` plus
   upstream commit `7bb8bdf` into `build/aquamarine`. The session and the
   smoke harness prepend that directory on `LD_LIBRARY_PATH`.
4. First run `session/hyprland-smoke.sh` from the branch. It uses
   `ft-screens --no-vr` on **unique** Wayland/control socket names with an
   isolated Hyprland runtime and auto-exits after 15 seconds. It never
   registers SteamVR panels. The harness fails unless every output logs a
   mapped `screen N: commit` of the requested size and the client stays
   connected. It runs
   `wayland-info | session/hyprland-protocol-check.py` against the **actual**
   `ft-screens` socket before starting Hyprland. Protocol version checks are
   necessary but do not prove protocol behavior or DMA-BUF import. To exercise extra
   outputs without VR, set `FT_SCREEN_COUNT=2`.
5. Launch the experimental branch only when you're ready to test. From that
   checkout, `FT_DESKTOP_SESSION=hyprland ./session/frametop-session.sh`
   starts the Hyprland layout on sockets `ft-hyprland-0` and `ft_hyprland`.
   With no layout file that is one 1920×1080 panel, 1.5 m wide. It does not
   read `ft-layout screen-args` and does not change
   `~/.config/frametop-layout.json`. Cleanup kills only the `ft-screens` whose command line
   carries `ft-hyprland-0`, and Hyprland started with this tree's minimal
   config (`session/hyprland-stop.sh` does the same). The Plasma path still
   uses the saved layout and its own `ft-screens-0` process. There is no
   separate Steam launcher: run this checkout's session script. Do not
   symlink it over the installed one.
6. Collect `/tmp/frametop-hyprland-screens.log` (not the Plasma
   `/tmp/frametop-screens.log`); check SteamVR
   frame timing and Plasma fallback before expanding to multiple outputs.

With `FT_QS_SMOKE=1`, the smoke harness starts the staged shell in isolated
config, data, and state directories. `FT_APP_PROBE=1` also opens Kitty,
Dolphin, Firefox, and both Frametop settings windows; the harness checks the
Kitty and settings window classes. Use a temporary copy of the staged shell
configuration and theme for the probe, because the shell can update its own
configuration. Profile restoration is disabled in this test.

The smoke harness may start Frametop's container and will create temporary
runtime paths; it does **not** stop or modify the existing Frametop process.
It verifies host protocol negotiation and surface commits but **cannot**
validate SteamVR buffer import, panel rendering or controller interaction.

## Session mechanics

Hyprland is launched through `scripts/in-box` with an absolute Wayland
socket path, separate config/state folders (`~/.config/frametop/hyprland`
and `~/.local/state/frametop/hyprland`) and a per-launch isolated runtime.
The nested runtime directory is a short `/tmp/ftH.*` path. Hyprland's
instance socket is `$XDG_RUNTIME_DIR/hypr/<abi signature>/.socket2.sock`,
and `sockaddr_un.sun_path` holds 108 bytes; the user runtime directory
makes that path too long and Hyprland disables IPC.
`dbus-run-session` owns the nested bus; `HYPRLAND_NO_SD_VARS=1` and
`HYPRLAND_NO_SD_TARGET=1` prevent nested Hyprland from importing variables
or activating/stopping SteamOS user graphical session targets. The current
compositor runs inside the Fedora dev container, not directly on the host.

`session/hyprland-frame.lua` is the config the experimental session loads.
`FT_HYPR_CONFIG_ROOT` selects the Hyprland tree (the staged copy under
`stage/config/hypr`). When that file is absent it falls back to
`~/.config/hypr/hyprland.lua`, then to one terminal and `SUPER+Return` /
`SUPER+SHIFT+E`. `session/frame-hypr/` is ahead of the selected tree on
`package.path` and replaces startup only: Quickshell via
`session/frame-quickshell.sh`, and no hypridle, brightness agent, or login
autostart. Quickshell reads `FT_USER_CONFIG_HOME` (the staged
`stage/config`, whose `quickshell/ii` is the end-4 copy). A missing `qs`
or a missing shell exits that helper with status 0; Hyprland keeps running.
`session/hyprland-minimal.lua` remains the fallback's reference.
`FT_HYPRLAND_CONFIG` still selects another file. The session does not write
`~/.config/hypr` or `~/.config/quickshell`. `session/frame-hypr/hyprland/services/create_custom_config.lua`
replaces the laptop startup hook that would create `~/.config/hypr/custom`.

Before Hyprland starts, the session writes
`$XDG_RUNTIME_DIR/frametop-hyprland.route` with its pid, the exact runtime
directory, the Wayland socket, the control name `ft_hyprland`, and the
staged config home. The exit trap and `hyprland-stop.sh` remove that file.
A dead pid is not a session. `frame-desktop-action.sh` refuses to run when
the route's runtime has zero or more than one Hyprland signature directory.
Host commands re-enter the Fedora container through `scripts/in-box` with
that runtime and signature. The script name is `frame-desktop-action.sh`.
Launcher IPC is `qs -c ii ipc --any-display call search toggle` so it can
see the shell when the caller is not the same display connection.
The Fedora container has Quickshell 0.2.1
(`dacfa9de829ac7cb173825f593236bf2c21f637e`). The laptop shell was written
for 0.3.2 (`4f508be`). The 0.2.1 package is what the isolated smoke loaded.
The broken first-test appearance was the missing theme, not that version
gap. The laptop shell reads `~/.config/illogical-impulse/config.json`,
`~/.local/state/quickshell/user/generated/colors.json`, a wallpaper, and
the families Google Sans Flex, Readex Pro, Space Grotesk, JetBrainsMono
Nerd Font, and Material Symbols Rounded. `session/stage-end4.py` copies
those into `stage/` (fonts included) and does not write `~/.config`.
`session/frame-theme.sh` seeds the session state directory from that copy
and points fontconfig at the staged fonts for Quickshell only. Staged QML is patched where it reads properties the shell schema does not
define (`forceMonitor`, `widgetPadding`, and an empty tab target); those
are the same files on Quickshell 0.3.2. The staged conflict killer returns
before it runs when `FT_FRAME_SESSION` is set, so it does not stop Plasma's
`kded6`. The session points PipeWire and Pulse at the host sockets and does
not start a second server. Bluetooth and UPower stay on SteamOS; the
container cannot authenticate to that system bus.
[end4-frame.md](end4-frame.md) lists the rest.

Starting Hyprland stops Plasma's `ft-screens` on `ft-screens-0` first, and
starting Plasma stops the Hyprland session. The two do not stay up together.
The compositor reports `keyboard hyprland <control>` when a panel is pointed
at, and keeps the last panel active after the pointer leaves. A click on
another SteamVR overlay, a hidden desktop, or the dashboard gives focus back.
The control name is that session's socket, and Hyprland follows the pointed
monitor. An older compositor still sends the unnamed
`keyboard hyprland`; that keeps the default route and does not take the
keyboard back from a panel that just named itself. The message is not
`keyboard steam`, so Plasma keeps that signal. Chord buttons follow the
Hyprland signal. They drop when the dashboard is in front, the route file
disappears, or the focus message stops. Quickshell's launcher also reads
`~/.local/share/applications`, which is where Steam and the Frametop settings
desktop files are.

While that panel has focus, the relay does not treat a Meta tap as the Steam
menu, and it grabs the keyboard for the panel even if Plasma has also claimed
the desktop. Keys are delivered as evdev codes, which is what Hyprland's nested backend expects. The laptop config's scale
of 1.25 is overridden to 1 on this panel. App keybinds call `session/frame-app.sh` instead of the laptop's `~/.config/hypr` scripts. Controller workspace, window, and close actions use Hyprland's Lua dispatchers (`hl.dsp.focus`, `hl.dsp.window.move`, `hl.dsp.window.close`). `hyprctl dispatch workspace` is rejected by this build.
Controller clicks are also read from vrserver's input stream, because the
helper's action sets stay inactive until SteamVR delivers overlay-global input.

The installed input relay sends keys to `@ft_screens`. The experimental
compositor listens on `@ft_hyprland`, and `session/hyprland-key-forward.py`
holds `@ft_screens` while Plasma is down and proxies every compositor
command except leftover Plasma `place`/`size` and KWin float messages.
Queries that need a reply (`get`, `remotes`, `ext`, `state`) are answered
back to the sender, so gaze, calibration, and the extension client keep
working without a rebuild. `layout/ft-layout` talks to `@ft_hyprland` and
`~/.config/frametop/hyprland-layout.json` whenever `ft-hyprland-0` is up,
including Hide/Show Screens, Reset Screen Layout, profiles, pins, and
remote displays. The relay in this checkout, once it is the running unit,
sends desktop input to the route's control socket while the Hyprland panel
has focus. Chord buttons are requested in that same case.

## Remaining gates

- [x] Live protocol audit for Aquamarine `wl_compositor` 6,
      `wl_seat` 9, `xdg_wm_base` 6, `wl_shm` 1, and
      `zwp_linux_dmabuf_v1` 4 with feedback. ft-screens on wlroots 0.20.2
      advertises each of those versions; `wayland-info` against a `--no-vr`
      socket matches. Version checks do not prove DMA-BUF import.
- [x] `--no-vr` DMA-BUF commits from nested Hyprland. One 1280×720 output
      and two 1280×720 outputs both map `aquamarine - WAYLAND-N` toplevels
      and report buffer commits on the control socket. This does not import
      those buffers into SteamVR.
- [x] SteamVR `ImportDmabuf` and one 1280×720 panel. The first live session
      mapped `aquamarine - WAYLAND-1`, logged modifiers SteamVR can import,
      and did not log `ImportDmabuf failed`. Frame pacing followed the
      existing in-view rate until the panel was focused.
- [x] Controller click, keyboard focus, and scroll on that one-terminal
      session. Keyboard shortcuts needed the `@ft_screens` forwarder; the
      session starts it now. `SUPER+Return` and `SUPER+SHIFT+E` are Hyprland
      binds and do nothing until the key arrives at this compositor.
- [x] Additional outputs and correct output-to-panel mapping. Slot identity
      is `hypr-N` in `hyprland-layout.json`; Aquamarine `WAYLAND-N` names are
      not the slot.
- [x] Pause/resume, Hide/Show Screens, Reset Screen Layout, profiles, pins,
      and gaze/extension queries against `@ft_hyprland`.
- [ ] Hyprland adapters for KWin-specific floating windows, VNC/remote
      desktop. Those stay Plasma-only; the Hyprland VR keyboard focus bridge
      is implemented but still needs headset validation.
- [ ] Frame-specific end-4/Quickshell profile loaded in VR. A staged copy
      lives under `stage/config` and is not the user's `~/.config`. Battery,
      brightness, and suspend modules are still in the shell; a module
      error stays inside the Quickshell process. The right-controller
      profile is `session/frame-controller-profile.json`. It is not merged
      into `~/.config/frametop-input.json`, and the installed input relay
      is not restarted by these changes. R1, R3, and stick scroll stay
      SteamVR's click and scroll. Trigger is a modifier only after that
      profile is active: face buttons change workspace or move the focused
      window, and trigger plus a face button launches an app. Trigger+R3
      closes one window. R1 stays a left click. What the Frame session
      runs, adapts, or leaves out is [end4-frame.md](end4-frame.md).

## Controller chords

`input/controller_chords.py` decides a press. The trigger never launches
anything. Releasing the trigger and the other button in either order does
not launch a second action. R1 stays SteamVR's left click. R3 stays
SteamVR's right click and is not in the helper's bind list. While the
trigger is already down, the thumbstick press runs `close` once. The relay
also sends `chord-click 1`, and ft-screens swallows the controller's right
click (hand controller or the `ft_pointer` virtual controller) so that
press is not a right click. A real mouse right click is neither source and
is still delivered. If the overlay click is the report that arrives first,
`chord-fired` runs the same close; the latch drops the second report.
Releasing the trigger before R3 still swallows the matching button-up.
The second live test showed Trigger+R1 could not do this: every R1 press
arrived while the guard was disarmed, so the close never ran. A VR game,
pause, typing leaving the desktop, or the route file disappearing clears
the modifier. The buttons stay unbound while `controller_in_games` is set.
The commands are `command:frame-desktop-action.sh`, the file on `PATH`.
The session starts `frame-desktopd.py` inside the container. A press sends
the action name to that process. Starting a container for every press took
about a third of a second; the socket path does not.

## Relay deployment

The user unit `frametop-input-relay.service` is `Type=notify` with
`FileDescriptorStorePreserve=yes`. The unit file still names
`~/frametop-api/input/input-relay.py`. The Hyprland install adds a drop-in,
`~/.config/systemd/user/frametop-input-relay.service.d/hyprland.conf`, that
replaces `ExecStart` with the pinned relay. Restarting the unit keeps the
virtual mouse and keyboard file descriptors in systemd's store. Do not
`systemctl --user clean --what=fdstore` on that unit.

`controller_chords` in `~/.config/frametop-input.json` is the Trigger map,
and `controller_in_games` is false so those chords are not active in a game.
They bind only while the Hyprland route file exists and the panel is focused.
Stopping the session removes the route file and releases the chords.

`frametop-desktop rollback` restores the desktop entry, the input rules, the
layout file, and the relay drop-in from the snapshot taken at install, then
restarts the relay and starts the Plasma session. It does not clear the
file-descriptor store.
