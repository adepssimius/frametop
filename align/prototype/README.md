# Monitor alignment prototype

This puts Frametop's remote display panels on top of the physical monitors they stream. It's a working prototype, driven by hand from a Mac; nothing in Frametop calls it yet. It's here to keep what was learned while the real feature is built.

## How it works

1. Each display shows a green grid and four AprilTags (36h11). Each display has its own tag IDs, so any camera frame says which monitor it's looking at.
2. `stream.py`, on the headset, sends the side tracking cameras' frames (through ft-camd's ring) and the head poses (`ft_poselog.cpp`) to the Mac.
3. `live_multi.py`, with `live_core.py`, detects the tags and turns each corner into a ray in SteamVR's standing universe. It fits each monitor separately, as a rigid pose at a known size, about three times a second.
4. `panelctl.py` sends the result to ft-screens: `width N metres`, `curve N 0`, `pose N matrix`.
5. Clicking a display locks it.

`join_curve.py` then makes two neighbouring panels arcs of one cylinder, tangent at the seam. Its default radius keeps the turn already measured between the monitors, which came to 2.15 m on two 31.5-inch monitors at 19 degrees.

## What the tests found

Tested on 2026-11-02 on one Steam Frame and a Mac with two OMEN 32 monitors and its built-in display, judged by eye against the real screens.

- Holding still doesn't work: the angle comes out about 5 degrees off, however long you wait. Head movement matters most, up and down as well as side to side.
- Two-camera stereo alone measured a monitor 7-10% too small. Many viewpoints came within about 2% of its spec.
- Corner error stops improving at a few millimetres. The error figure shown is the fit's corner spread times 4, because replaying a capture put the actual worst corner at up to about 3.7 times that spread, in 90% of cases.
- All three displays locked about 26 seconds after launch, including about 6 seconds of connecting. A 30 cm built-in display needs a closer look than the monitors.
- Room coordinates don't survive a SteamVR restart: the saved position ended up about 90-144 degrees away. The room map is restored under the same ID, so why it moved is still open.
- Setting the headset down lost the alignment briefly, and it recovered on its own. `Standing origin changed` can repair alignment as well as break it, so it isn't a reason to realign automatically.

## Not done

- Nothing is saved: positions last until the session restarts.
- The solver runs on the Mac. It belongs on the headset, with a small marker helper per host OS.
- Nothing starts it from Frametop. The plan is an arrangement on the Layout & profiles page.
- The built-in display's size is its spec plus an assumed 2%, and `join_curve.py` only joins panels of equal width.
- The panels' curved surface was never measured directly. The seam relies on the calculation and on how it looks.

## Running it

It needs more than this folder, and isn't packaged:

- Mac: Python with `opencv-contrib-python-headless`, `numpy`, `scipy`, `pyobjc-framework-Cocoa`.
- Next to `live_core.py`: `hands/tools/calib.py`, the headset's `/persist/xrservice.json` and `device_config.json` copied to `root/persist/`, and the images from `make_marker.py` and `make_grid.py`.
- Headset: `hands/build/ft-camd` with its capabilities (`hands/run.sh caps`), `stream.py` and `panelctl.py` copied to `/tmp`, and `ft_poselog.cpp` built in the `dev` container against the OpenVR SDK from `scripts/openvr.sh`.

Paths, the display layout and the panel numbers are hardcoded for the test machine.
