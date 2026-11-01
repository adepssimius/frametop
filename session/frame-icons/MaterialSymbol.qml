import qs.modules.common
import QtQuick
import Quickshell
import "material-glyphs.js" as Glyphs

// The icon names are ligatures. Qt on this container does not apply them,
// so the painted text is the font's own codepoint for that name.
Item {
    id: root
    property real iconSize: Appearance?.font.pixelSize.small ?? 16
    property real fill: 0
    property real truncatedFill: fill.toFixed(1)
    property string text
    property alias color: glyph.color
    property alias font: glyph.font
    property alias horizontalAlignment: glyph.horizontalAlignment
    property alias verticalAlignment: glyph.verticalAlignment
    property alias renderType: glyph.renderType
    property alias style: glyph.style
    property alias styleColor: glyph.styleColor
    property bool animateChange: false
    implicitWidth: glyph.implicitWidth
    implicitHeight: glyph.implicitHeight

    FontLoader {
        id: materialSymbols
        source: {
            const path = Quickshell.env("FT_FRAME_FONT_MATERIAL") || ""
            if (!path) return ""
            return "file://" + path.split("/").map(part => encodeURIComponent(part)).join("/")
        }
    }

    Text {
        id: glyph
        anchors.centerIn: parent
        text: Glyphs.map(root.text || "")
        renderType: Quickshell.env("FT_FRAME_SESSION") ? Text.QtRendering : Text.NativeRendering
        color: Appearance?.m3colors.m3onBackground ?? "black"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        font {
            hintingPreference: Font.PreferNoHinting
            preferShaping: true
            family: materialSymbols.status === FontLoader.Ready ? materialSymbols.name : (Appearance?.font.family.iconMaterial ?? "Material Symbols Rounded")
            pixelSize: root.iconSize
            weight: Font.Normal + (Font.DemiBold - Font.Normal) * root.truncatedFill
        }
    }

    Behavior on fill {
        NumberAnimation {
            duration: Appearance?.animation.elementMoveFast.duration ?? 200
            easing.type: Appearance?.animation.elementMoveFast.type ?? Easing.BezierSpline
            easing.bezierCurve: Appearance?.animation.elementMoveFast.bezierCurve ?? [0.34, 0.80, 0.34, 1.00, 1, 1]
        }
    }
}
