# Frametop extension API (draft v1)

This is a **small external control contract**, not a dynamic-library loader or a
general plugin manager. It is intentionally independent of any Tovakai feature.
The upstream compositor remains the owner of screen state, tracking and OpenVR
overlay handles. External programs can use this interface without patching
`screens/vr.cpp`, copying SteamVR state, or writing Frametop's config files.

## Transport and discovery

The interface uses the existing Frametop control socket: abstract Linux
`AF_UNIX / SOCK_DGRAM` `@ft_hyprland` when the Hyprland desktop is up, otherwise `@ft_screens`. Bind your own *different* abstract
address before sending so the compositor can reply. Commands and replies are
UTF-8, one command per datagram. Every reply begins with `ok` or `error`.

```text
ext api
  ok 1

ext caps
  ok screen.status screen.opacity screen.move
```

Version 1 adds commands without changing existing `place`, `get`, `pin`,
`curve`, or `ft-layout` commands. Check both API version and each capability
before relying on an operation. **No event subscription, plugin installation,
gaze samples, follow modes, toolbar integration or persistence yet.** Those
require further design and dedicated tests; this first slice is not a claim that
Frametop already has a complete plugin system.

## Screen controls

Screen indices are **1-based**. In v1 these controls apply to local desktop
screens, not floating windows or remote displays.

```text
ext status N
  ok opacity CURRENT target TARGET fading 0|1 moving 0|1 pinned none|left|right|head

ext opacity N ALPHA MILLISECONDS
  ok

ext move N X Y Z YAW PITCH ROLL MILLISECONDS
  ok
```

- `ALPHA` is in **0..1**. `ext opacity N 1 0` removes a prior override.
  The alpha multiplies existing wrist-facing fade; it never bypasses ordinary
  show/hide, game-pause or visibility rules. A fully faded screen is hidden,
  including its laser hit area.
- Position is in metres, in SteamVR's **standing-world coordinate system**.
  Facing yaw, pitch and roll are degrees, as with the existing `place` command.
- Duration is **0..10000 ms**; 0 applies immediately. Positive values run in
  the compositor's existing VR frame tick using cosine easing. The move uses
  shortest-arc quaternion rotation, so crossing +/-180 degrees doesn't spin a
  screen all the way around. The proposed spatial profile default is 450 ms.
- Repeating an opacity or move command transitions from the current value
  to the new target. A regular `place` command, a pin, or a controller drag
  cancels an in-progress extension move.
- `ext move` is rejected while the screen is pinned or being dragged.
  Callers must explicitly unpin the screen through normal Frametop controls
  if they want to move it in world space.
- These are **runtime overrides**. They do not silently modify layout/profile
  files, and they reset when `ft-screens` restarts. A profile extension must
  implement its own persistence and replay.

## Python client

Only the standard library is required. Use it as a module or a command:

```sh
python3 extensions/ft_ext.py info
python3 extensions/ft_ext.py status 1
python3 extensions/ft_ext.py opacity 1 0.6 --ms 250
python3 extensions/ft_ext.py move 1 0 1.5 -1.0 0 0 0 --ms 450
```

```python
from extensions.ft_ext import Frametop

ft = Frametop()
assert ft.api_version() >= 1
assert "screen.move" in ft.capabilities()
ft.move(1, 0, 1.5, -1, 0, 0, 0, duration_ms=450)
ft.opacity(1, 0.6, duration_ms=250)
```

Run contract tests with:

```sh
python3 extensions/tests/test_ft_ext.py
g++ -std=c++17 -Wall -Wextra -Werror screens/tests/extension-motion-test.cpp -o /tmp/ft-ext-motion-test
/tmp/ft-ext-motion-test
```

The tests use a fake Unix datagram endpoint and a pure-C++ matrix type. They do
not need a Steam Frame, SteamVR or a headset. The compositor integration still
**needs live device testing** before the API should be called stable.

## Guardrails and next steps

- The existing local control socket is a trusted-user control plane, **not a
  sandbox or a permission boundary**. Only install extensions you trust. A
  future registry must not automatically execute arbitrary downloaded code.
- Extensions must not steal SteamVR input focus, replace Frametop's overlay
  handles, or write to another extension's state.
- APIs must be general-purpose. Our first consumer should be an external
  spatial profile implementation using these transition commands and its
  existing JSON profile format.
- Likely future needs: a **read-only event stream** with backpressure and
  versioned payloads, eye-gaze targets without enabling gaze pointer mode,
  soft-follow behaviors in the render tick, and optional independent toolbar
  overlays. These are **not implemented** in v1.
- Keep upstream updates easy to merge. Prefer new helper modules and a small
  number of compositor hooks instead of transplanting legacy Frametop source.
