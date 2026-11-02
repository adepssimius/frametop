# Monitor alignment

Puts each remote display's panel on top of the physical monitor it streams, so a monitor you can see through Room View and its panel are in the same place. It's a session's work, not a saved layout, because SteamVR's room coordinates can move between sessions.

## Using it

Open **Align to My Monitors** from the menu, or press Meta+Shift+A, or choose **Align to my monitors** on the Layout & profiles page of Frametop Display Settings. Each monitor shows markers and the panels move onto them as you move your head. Each one locks by itself once its figure has stayed under 5 mm for 3 seconds, and its stream comes back. Open the entry again to stop early. It stops by itself after 5 minutes. Check **Join … into one curved monitor** in Display Settings first to make two neighbouring monitors one curved monitor.

`ft-layout align` does the same from a terminal, and `ft-layout align status | lock N|all | stop` control it.

A display locks only after being seen from at least 12 places (a 5 cm grid), so a still head never locks. A monitor being measured for the first time needs 30 places and a steady width, because its size is kept for good.

It needs ft-camd's capabilities once (`hands/run.sh caps`, which asks for the password), and each computer's host setup run with this version, which adds the marker app. Hand tracking doesn't have to be on.

## How it works

1. Each display's stream switches to the host's `FrametopAlign` app, using the pairing Frametop already has. There's no new port or service on the computer. Sunshine runs one app at a time and Frametop otherwise never quits one, so this quits the running app first (HTTPS `/cancel`).
2. The app shows four AprilTags (36h11) on the real monitor. They're placed as fractions of the screen, so resolution and scaling don't matter. `host/macos/align-markers.js`, `host/windows/align-markers.ps1` and `align/solver.cpp` must agree on the layout.
3. `align/build/ft-align` reads the side tracking cameras from ft-camd's ring and the head's pose from OpenVR, and finds the tags with the `apriltag` library. Each tag's ID says which monitor it's on, so a frame can feed several monitors at once.
4. A thread per display fits that monitor's pose in the standing universe, at most 4 times a second and only when it has something new, and moves its panel with `pose N matrix`. The first time, the fit also measures the monitor's size, which is kept in `frametop-layout.json` as `physical` once the fit is good enough.
5. A display's stream comes back when it's locked. Everything comes back if anything fails.

`layout/ft_align.py` runs all of this. `layout/ft-layout align` is its command line, and Display Settings talks to it on the abstract socket `@ft_align`.

### Mac and Windows differ

| | Mac | Windows |
| --- | --- | --- |
| Servers | One Sunshine instance per display | One Vibepollo for every display |
| Marker app | One per display, each showing its own tags (4N to 4N+3, for instance N) | One app, showing every monitor's tags (4(n-1) to 4(n-1)+3, for `\\.\DISPLAYn`) |
| Which panel starts it | Every panel | The first panel |
| While it runs | That panel shows its markers | The first panel shows the primary display; the others keep their streams |
| Streams come back | As each is locked | Once, at the end. Ending the app drops the others, and they reconnect by themselves in about 4 s |

Windows monitors are matched to panels through Vibepollo's monitor list (`ft-layout remote monitors`): a panel's `display:{id}` gives its `\\.\DISPLAYn`. A monitor that isn't active on the computer fails with a message saying so. Virtual displays are skipped, because they have no physical monitor.

## Joining two monitors

A join makes two equal panels arcs of one cylinder, tangent at the seam (`join_panels` in `layout/ft_align.py`). The default radius keeps the turn the two panels already have between them, so they go on facing as the real monitors do: 19 degrees across two 31.5-inch monitors came to 2.15 m. The seam closes, so the panels no longer sit exactly over their monitors, and the bezels are gone. `align_join_radius` in the layout overrides the radius.

## What the tests found

On a Steam Frame, with a Mac and a Windows PC, in November 2026:

- **Holding still isn't enough.** A still pass came out about 1 degree and 14 mm off. Moving your head matters most, up and down as well as side to side.
- **The figure.** It's the fit's worst-corner spread, times 4, and more when the head saw the monitor from few places. Replaying a capture put the real error at up to 3.7 times the spread in 90% of cases, against a fit from the same frames. A still pass would otherwise read 5.8 mm at a real 14 mm. It can't see errors common to every frame, so the view through the headset is the real check.
- **Two-camera stereo alone** measured a monitor 7-10% too small. Many viewpoints came within about 2% of its spec.
- **Room coordinates don't survive a SteamVR restart.** A saved position ended up far off, though the room map is restored under the same ID. Why is still open. `Standing origin changed` can also repair alignment after the headset is set down, so it isn't a reason to realign automatically.
- **Costs.** About 45 ms a frame to find tags, on two threads, and about 2 ms a fit. These are from replays, not from running beside SteamVR and streams.

### Windows

- With monitors on the Intel graphics, quitting an app makes Vibepollo re-test its encoders and pick NVENC, which then loops and can crash `sunshine.exe`. `encoder = quicksync` and `adapter_name = Intel(R) Graphics` in `sunshine.conf` fix it. The setup doesn't handle this yet.
- The marker script must exit when its windows close, or Vibepollo force-closes it after 5 s.
- Vibepollo's default `Desktop` app turns the other monitors off, so `FrametopAlign` sets `display-output` empty and `dd-configuration-option` to `disabled`.

## Not done

- Nothing has run end to end on Windows, and the Windows marker script has only been checked as far as its test version.
- Offering a realign when the room coordinates move.
- Anchoring panels to SteamVR's saved room map, which might mean realigning far less often.
- The Arcturus cameras (`ft-camd --with-color`), which might reduce the movement needed. Frametop's notes call them unreliable when worn.
- Panels of different widths in a join.
- An arrangement of its own in the Arrangement list, so a profile can remember these displays.
