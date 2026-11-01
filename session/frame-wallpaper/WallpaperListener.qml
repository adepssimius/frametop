pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import qs.modules.common

// Per-monitor wallpapers for the Frame session.
// Adapted from end-4/dots-hyprland pull 2245 by Sevilze (GPL-3.0-or-later).
// Assignments are stored as hypr-N. This asks wallpaper_identity.py to
// resolve those ids through the live output map, so a recreated WAYLAND-N
// keeps its image. The shared Material You palette is untouched here.
Singleton {
    id: root
    property var effectivePerMonitor: ({})
    readonly property bool multiMonitorEnabled: Config.options.background?.multiMonitor?.enable ?? false

    function refresh() {
        const session = Quickshell.env("FT_FRAME_SESSION")
        if (!session) return
        resolve.command = ["python3", session + "/wallpaper_identity.py", "effective"]
        resolve.running = true
    }

    Process {
        id: resolve
        stdout: StdioCollector {
            id: resolveOut
            onStreamFinished: {
                try {
                    const parsed = JSON.parse(resolveOut.text || "{}")
                    if (JSON.stringify(parsed) !== JSON.stringify(root.effectivePerMonitor))
                        root.effectivePerMonitor = parsed
                } catch (e) {
                    root.effectivePerMonitor = ({})
                }
            }
        }
    }

    onMultiMonitorEnabledChanged: refresh()
    Component.onCompleted: refresh()

    Timer {
        interval: 2000
        running: true
        repeat: true
        onTriggered: root.refresh()
    }
}
