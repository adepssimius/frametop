#!/usr/bin/env python3
"""Copy the laptop Hyprland and end-4 trees into an explicit stage directory.

The copy is what the experimental session reads. It does not write
~/.config/hypr or ~/.config/quickshell. Symlinks that leave the source tree
are skipped. Files that contain a private key are skipped.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

SKIP_DIRS = {".chatgpt-integration", "__pycache__", ".venv", "venv", ".git"}
SKIP_SUFFIXES = (".old", ".bak", ".pem")
SECRET_MARKERS = ("BEGIN PRIVATE KEY", '"private_key"', "BEGIN OPENSSH PRIVATE KEY")


def user_config_blocked(dest: Path) -> bool:
    home = Path.home().resolve()
    try:
        resolved = dest.resolve()
    except OSError:
        resolved = dest
    blocked = home / ".config"
    return resolved == blocked or blocked in resolved.parents


def _skip_name(name: str) -> bool:
    if name in SKIP_DIRS or name.startswith("backup-"):
        return True
    return name.endswith(SKIP_SUFFIXES)


def _has_secret(path: Path) -> bool:
    try:
        if path.stat().st_size > 1_000_000:
            return False
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(marker in text for marker in SECRET_MARKERS)


def copy_tree(src: Path, dest: Path) -> list[str]:
    """Copy src into dest. Returns notes for skipped paths."""
    src = src.resolve()
    notes = []
    if not src.is_dir():
        raise SystemExit(f"frametop: stage source is not a directory: {src}")
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        kept = []
        for name in dirnames:
            child = Path(dirpath) / name
            if _skip_name(name):
                notes.append(f"skip {child}")
                continue
            if child.is_symlink():
                target = child.resolve()
                if not target.is_relative_to(src):
                    notes.append(f"skip symlink {child}")
                    continue
            kept.append(name)
        dirnames[:] = kept
        rel = Path(dirpath).relative_to(src)
        (dest / rel).mkdir(parents=True, exist_ok=True)
        for name in filenames:
            child = Path(dirpath) / name
            if _skip_name(name):
                notes.append(f"skip {child}")
                continue
            target = dest / rel / name
            if child.is_symlink():
                link = os.readlink(child)
                resolved = (child.parent / link).resolve()
                if not resolved.is_relative_to(src):
                    notes.append(f"skip symlink {child}")
                    continue
                if target.is_symlink() or target.exists():
                    target.unlink()
                target.symlink_to(link)
                continue
            if _has_secret(child):
                notes.append(f"skip secret {child}")
                continue
            shutil.copy2(child, target, follow_symlinks=False)
    return notes


FONT_FAMILIES = (
    "Google Sans Flex",
    "Readex Pro",
    "Space Grotesk",
    "Material Symbols Rounded",
    "JetBrainsMono Nerd Font",
)

SHELL_PATCHES = (
    (
        "quickshell/ii/modules/ii/notificationPopup/NotificationPopup.qml",
        "Config.options.notifications.forceMonitor",
        "Config.options.notifications.monitor",
    ),
    (
        "quickshell/ii/modules/ii/bar/BarContent.qml",
        "padding: workspacesWidget.widgetPadding",
        "padding: 5",
    ),
    (
        "quickshell/ii/modules/common/widgets/ToolbarTabBar.qml",
        "property Item targetItem: contentItem.children[root.currentIndex]\n",
        "property Item targetItem: contentItem.children[root.currentIndex] ?? null\n",
    ),
    (
        "quickshell/ii/modules/common/widgets/ToolbarTabBar.qml",
        "index: activeIndicator.targetItem.x\n",
        "index: activeIndicator.targetItem?.x ?? 0\n",
    ),
    (
        "quickshell/ii/modules/common/widgets/ToolbarTabBar.qml",
        "index: activeIndicator.targetItem.x + activeIndicator.targetItem.width",
        "index: (activeIndicator.targetItem?.x ?? 0) + (activeIndicator.targetItem?.width ?? 0)",
    ),
    (
        "quickshell/ii/services/ConflictKiller.qml",
        "            if (Config.ready) checkConflictsProc.running = true",
        "            if (Quickshell.env(\"FT_FRAME_SESSION\")) return\n"
        "            if (Config.ready) checkConflictsProc.running = true",
    ),
    (
        "quickshell/ii/services/Brightness.qml",
        "    function increaseBrightness(): void {\n",
        "    function increaseBrightness(): void {\n"
        "        if (Quickshell.env(\"FT_FRAME_SESSION\")) return\n",
    ),
    (
        "quickshell/ii/services/Brightness.qml",
        "    function decreaseBrightness(): void {\n",
        "    function decreaseBrightness(): void {\n"
        "        if (Quickshell.env(\"FT_FRAME_SESSION\")) return\n",
    ),
    (
        "quickshell/ii/services/Brightness.qml",
        "    onMonitorsChanged: {\n        ddcMonitors = [];\n",
        "    onMonitorsChanged: {\n"
        "        if (Quickshell.env(\"FT_FRAME_SESSION\")) return\n"
        "        ddcMonitors = [];\n",
    ),
    (
        "quickshell/ii/modules/common/widgets/MaterialSymbol.qml",
        "import qs.modules.common\nimport QtQuick\n",
        "import qs.modules.common\nimport QtQuick\nimport Quickshell\n",
    ),
    (
        "quickshell/ii/modules/common/widgets/MaterialSymbol.qml",
        "    renderType: Text.NativeRendering\n",
        "    // Qt's native text path on this container drops Material Symbol ligatures.\n"
        "    renderType: Quickshell.env(\"FT_FRAME_SESSION\") ? Text.QtRendering : Text.NativeRendering\n",
    ),
    (
        "quickshell/ii/modules/common/widgets/MaterialSymbol.qml",
        "    // Qt's native text path on this container drops Material Symbol ligatures.\n"
        "    renderType: Quickshell.env(\"FT_FRAME_SESSION\") ? Text.QtRendering : Text.NativeRendering\n"
        "    font {\n"
        "        hintingPreference: Font.PreferNoHinting\n"
        "        family: Appearance?.font.family.iconMaterial ?? \"Material Symbols Rounded\"\n",
        "    // Qt's native text path on this container drops Material Symbol ligatures.\n"
        "    // The file path is the font next to the Frame theme, so a second shell\n"
        "    // does not depend on fontconfig search order inside the container.\n"
        "    FontLoader {\n"
        "        id: materialSymbols\n"
        "        source: {\n"
        "            const path = Quickshell.env(\"FT_FRAME_FONT_MATERIAL\") || \"\"\n"
        "            if (!path) return \"\"\n"
        "            return \"file://\" + path.split(\"/\").map(part => encodeURIComponent(part)).join(\"/\")\n"
        "        }\n"
        "    }\n"
        "    renderType: Quickshell.env(\"FT_FRAME_SESSION\") ? Text.QtRendering : Text.NativeRendering\n"
        "    font {\n"
        "        hintingPreference: Font.PreferNoHinting\n"
        "        family: materialSymbols.status === FontLoader.Ready ? materialSymbols.name : (Appearance?.font.family.iconMaterial ?? \"Material Symbols Rounded\")\n",
    ),
    (
        "quickshell/ii/services/ai/ChatGptBridge.qml",
        "import QtQuick\nimport Quickshell.Io\n",
        "import QtQuick\nimport Quickshell\nimport Quickshell.Io\n",
    ),
    (
        "quickshell/ii/services/ai/ChatGptBridge.qml",
        "    property bool onlineAllowed: true\n",
        "    property bool onlineAllowed: false\n",
    ),
    (
        "quickshell/ii/services/ai/ChatGptBridge.qml",
        "        command: [\"/home/tovakai/Projects/quickshell-chatgpt/.venv/bin/python\", \"-m\", \"bridge\", \"serve\"]\n",
        "        command: [\"/usr/bin/bash\", \"-c\", \"test -z \\\"$FT_FRAME_SESSION\\\" && test -x /home/tovakai/Projects/quickshell-chatgpt/.venv/bin/python && exec /home/tovakai/Projects/quickshell-chatgpt/.venv/bin/python -m bridge serve\"]\n",
    ),
    (
        "quickshell/ii/services/ai/ChatGptBridge.qml",
        "        workingDirectory: \"/home/tovakai/Projects/quickshell-chatgpt\"\n",
        "        workingDirectory: \"/tmp\"\n",
    ),
    (
        "quickshell/ii/scripts/colors/random/random_konachan_wall.sh",
        'illogicalImpulseConfigPath="$HOME/.config/illogical-impulse/config.json"\n',
        'illogicalImpulseConfigPath="${XDG_CONFIG_HOME:-$HOME/.config}/illogical-impulse/config.json"\n',
    ),
    (
        "quickshell/ii/scripts/colors/random/random_osu_wall.sh",
        'illogicalImpulseConfigPath="$HOME/.config/illogical-impulse/config.json"\n',
        'illogicalImpulseConfigPath="${XDG_CONFIG_HOME:-$HOME/.config}/illogical-impulse/config.json"\n',
    ),
    (
        "quickshell/ii/scripts/colors/switchwall.sh",
        '        check_and_prompt_upscale "$imgpath" &\n',
        '        if [ -n "${FT_FRAME_SESSION:-}" ] && [ -f "$FT_FRAME_SESSION/frame-wallpaper.sh" ]; then\n'
        '            # shellcheck disable=SC1091\n'
        '            . "$FT_FRAME_SESSION/frame-wallpaper.sh"\n'
        '            imgpath=$(frame_scale_wallpaper "$imgpath")\n'
        '        else\n'
        '            check_and_prompt_upscale "$imgpath" &\n'
        '        fi\n',
    ),
    (
        "quickshell/ii/scripts/colors/switchwall.sh",
        '        cd "$(xdg-user-dir PICTURES)/Wallpapers/showcase" 2>/dev/null || cd "$(xdg-user-dir PICTURES)/Wallpapers" 2>/dev/null || cd "$(xdg-user-dir PICTURES)" || return 1\n'
        '        imgpath="$(kdialog --getopenfilename . --title \'Choose wallpaper\')"\n',
        '        if [ -n "${FT_FRAME_SESSION:-}" ] && [ -f "$FT_FRAME_SESSION/frame-wallpaper.sh" ]; then\n'
        '            # shellcheck disable=SC1091\n'
        '            . "$FT_FRAME_SESSION/frame-wallpaper.sh"\n'
        '            imgpath=$(frame_pick_wallpaper) || exit 0\n'
        '        else\n'
        '            cd "$(xdg-user-dir PICTURES)/Wallpapers/showcase" 2>/dev/null || cd "$(xdg-user-dir PICTURES)/Wallpapers" 2>/dev/null || cd "$(xdg-user-dir PICTURES)" || return 1\n'
        '            imgpath="$(kdialog --getopenfilename . --title \'Choose wallpaper\')"\n'
        '        fi\n',
    ),
    (
        "quickshell/ii/scripts/colors/switchwall.sh",
        '        source "$(eval echo $ILLOGICAL_IMPULSE_VIRTUAL_ENV)/bin/activate"\n'
        '        "$SCRIPT_DIR"/scheme_for_image.py "$img" 2>/dev/null | tr -d \'\\n\'\n'
        '        deactivate\n',
        '        if [ -n "${FT_FRAME_SESSION:-}" ] && [ -f "$FT_FRAME_SESSION/frame-wallpaper.sh" ]; then\n'
        '            # shellcheck disable=SC1091\n'
        '            . "$FT_FRAME_SESSION/frame-wallpaper.sh"\n'
        '            frame_scheme_for_image "$img"\n'
        '            return\n'
        '        fi\n'
        '        source "$(eval echo $ILLOGICAL_IMPULSE_VIRTUAL_ENV)/bin/activate"\n'
        '        "$SCRIPT_DIR"/scheme_for_image.py "$img" 2>/dev/null | tr -d \'\\n\'\n'
        '        deactivate\n',
    ),
    (
        "quickshell/ii/scripts/colors/switchwall.sh",
        '    matugen "${matugen_args[@]}"\n'
        '    source "$(eval echo $ILLOGICAL_IMPULSE_VIRTUAL_ENV)/bin/activate"\n'
        '    python3 "$SCRIPT_DIR/generate_colors_material.py" "${generate_colors_material_args[@]}" \\\n'
        '        > "$STATE_DIR"/user/generated/material_colors.scss\n'
        '    deactivate\n'
        '    "$SCRIPT_DIR"/applycolor.sh\n',
        '    if [ -n "${FT_FRAME_SESSION:-}" ] && [ -f "$FT_FRAME_SESSION/frame-wallpaper.sh" ]; then\n'
        '        # shellcheck disable=SC1091\n'
        '        . "$FT_FRAME_SESSION/frame-wallpaper.sh"\n'
        '        frame_recolor "${matugen_args[@]}"\n'
        '        return\n'
        '    fi\n'
        '    matugen "${matugen_args[@]}"\n'
        '    source "$(eval echo $ILLOGICAL_IMPULSE_VIRTUAL_ENV)/bin/activate"\n'
        '    python3 "$SCRIPT_DIR/generate_colors_material.py" "${generate_colors_material_args[@]}" \\\n'
        '        > "$STATE_DIR"/user/generated/material_colors.scss\n'
        '    deactivate\n'
        '    "$SCRIPT_DIR"/applycolor.sh\n',
    ),
    (
        "quickshell/ii/scripts/colors/random/random_konachan_wall.sh",
        "ext=$(echo \"$link\" | awk -F. '{print $NF}')\n",
        'if [ -n "${FT_FRAME_SESSION:-}" ] && [ -f "$FT_FRAME_SESSION/frame-wallpaper.sh" ]; then\n'
        '    # shellcheck disable=SC1091\n'
        '    . "$FT_FRAME_SESSION/frame-wallpaper.sh"\n'
        '    ext=$(frame_image_ext "$link") || exit 1\n'
        'else\n'
        "    ext=$(echo \"$link\" | awk -F. '{print $NF}')\n"
        'fi\n',
    ),
    (
        "quickshell/ii/scripts/colors/random/random_konachan_wall.sh",
        'curl -A "$userAgent" "$link" -o "$downloadPath"\n',
        'curl -A "$userAgent" "$link" -o "$downloadPath"\n'
        'if [ -n "${FT_FRAME_SESSION:-}" ] && [ -f "$FT_FRAME_SESSION/frame-wallpaper.sh" ]; then\n'
        '    # shellcheck disable=SC1091\n'
        '    . "$FT_FRAME_SESSION/frame-wallpaper.sh"\n'
        '    frame_require_download "$downloadPath" || exit 1\n'
        'fi\n',
    ),
    (
        "quickshell/ii/scripts/colors/random/random_osu_wall.sh",
        "ext=$(echo \"$link\" | awk -F. '{print $NF}')\n",
        'if [ -n "${FT_FRAME_SESSION:-}" ] && [ -f "$FT_FRAME_SESSION/frame-wallpaper.sh" ]; then\n'
        '    # shellcheck disable=SC1091\n'
        '    . "$FT_FRAME_SESSION/frame-wallpaper.sh"\n'
        '    ext=$(frame_image_ext "$link") || exit 1\n'
        'else\n'
        "    ext=$(echo \"$link\" | awk -F. '{print $NF}')\n"
        'fi\n',
    ),
    (
        "quickshell/ii/scripts/colors/random/random_osu_wall.sh",
        'curl "$link" -o "$downloadPath"\n',
        'curl "$link" -o "$downloadPath"\n'
        'if [ -n "${FT_FRAME_SESSION:-}" ] && [ -f "$FT_FRAME_SESSION/frame-wallpaper.sh" ]; then\n'
        '    # shellcheck disable=SC1091\n'
        '    . "$FT_FRAME_SESSION/frame-wallpaper.sh"\n'
        '    frame_require_download "$downloadPath" || exit 1\n'
        'fi\n',
    ),
    (
        "quickshell/ii/modules/common/Config.qml",
        '                property string wallpaperPath: ""\n'
        '                property string thumbnailPath: ""\n'
        '                property bool hideWhenFullscreen: true\n',
        '                property string wallpaperPath: ""\n'
        '                property string thumbnailPath: ""\n'
        '                // Per-monitor images. Adapted from end-4/dots-hyprland pull 2245\n'
        '                // by Sevilze (GPL-3.0-or-later). enable false keeps one image\n'
        '                // on every monitor. Entries are {monitor, path, workspaceFirst,\n'
        '                // workspaceLast}; on the Frame, monitor is the hypr-N id.\n'
        '                property JsonObject multiMonitor: JsonObject {\n'
        '                    property bool enable: false\n'
        '                }\n'
        '                property list<var> wallpapersByMonitor: []\n'
        '                property bool hideWhenFullscreen: true\n',
    ),
    (
        "quickshell/ii/modules/ii/background/Background.qml",
        '        property bool wallpaperIsVideo: Config.options.background.wallpaperPath.endsWith(".mp4") || Config.options.background.wallpaperPath.endsWith(".webm") || Config.options.background.wallpaperPath.endsWith(".mkv") || Config.options.background.wallpaperPath.endsWith(".avi") || Config.options.background.wallpaperPath.endsWith(".mov")\n'
        '        property string wallpaperPath: wallpaperIsVideo ? Config.options.background.thumbnailPath : Config.options.background.wallpaperPath\n',
        '        // Wallpaper. Per-monitor data comes from WallpaperListener, which\n'
        '        // resolves hypr-N through the output map (end-4 PR 2245, Sevilze).\n'
        '        property var wallpaperData: {\n'
        '            const name = monitor?.name || ""\n'
        '            const found = name ? WallpaperListener.effectivePerMonitor[name] : null\n'
        '            if (found && found.path) return found\n'
        '            return { path: Config.options.background.wallpaperPath }\n'
        '        }\n'
        '        property string resolvedPath: wallpaperData.path || Config.options.background.wallpaperPath\n'
        '        property bool wallpaperIsVideo: resolvedPath.endsWith(".mp4") || resolvedPath.endsWith(".webm") || resolvedPath.endsWith(".mkv") || resolvedPath.endsWith(".avi") || resolvedPath.endsWith(".mov")\n'
        '        property string wallpaperPath: wallpaperIsVideo ? (wallpaperData.thumbnail || Config.options.background.thumbnailPath) : resolvedPath\n'
        '        property int parallaxFirst: wallpaperData.workspaceFirst || 1\n'
        '        property int parallaxLast: wallpaperData.workspaceLast || lastWorkspaceId\n',
    ),
    (
        "quickshell/ii/scripts/colors/switchwall.sh",
        'set_wallpaper_path() {\n'
        '    local path="$1"\n'
        '    if [ -f "$SHELL_CONFIG_FILE" ]; then\n'
        '        jq --arg path "$path" \'.background.wallpaperPath = $path\' "$SHELL_CONFIG_FILE" > "$SHELL_CONFIG_FILE.tmp" && mv "$SHELL_CONFIG_FILE.tmp" "$SHELL_CONFIG_FILE"\n'
        '    fi\n'
        '}\n',
        'frame_wallpaper_key() {\n'
        '    local monitor="$1"\n'
        '    if [ -z "$monitor" ]; then\n'
        '        echo ""\n'
        '        return\n'
        '    fi\n'
        '    if [ -n "${FT_FRAME_SESSION:-}" ] && [ -f "$FT_FRAME_SESSION/wallpaper_identity.py" ]; then\n'
        '        python3 "$FT_FRAME_SESSION/wallpaper_identity.py" key "$monitor"\n'
        '        return\n'
        '    fi\n'
        '    printf \'%s\\n\' "$monitor"\n'
        '}\n'
        '\n'
        'set_wallpaper_path() {\n'
        '    local path="$1"\n'
        '    local monitor="${2:-}"\n'
        '    local start_workspace="${3:-1}"\n'
        '    local end_workspace="${4:-10}"\n'
        '    local thumbnail="${5:-}"\n'
        '    if [ -f "$SHELL_CONFIG_FILE" ]; then\n'
        '        if [ -n "$monitor" ]; then\n'
        '            local key\n'
        '            key=$(frame_wallpaper_key "$monitor")\n'
        '            if [ -n "${FT_FRAME_SESSION:-}" ] && [ -f "$FT_FRAME_SESSION/wallpaper_identity.py" ]; then\n'
        '                python3 "$FT_FRAME_SESSION/wallpaper_identity.py" set "$key" "$path" "$start_workspace" "$end_workspace" "$thumbnail"\n'
        '            fi\n'
        '            jq --arg name "$key" --arg path "$path" --argjson startWs "$start_workspace" --argjson endWs "$end_workspace" --arg thumb "$thumbnail" \'\n'
        '                .background.wallpapersByMonitor = (\n'
        '                    (.background.wallpapersByMonitor // [])\n'
        '                    | map(select(.monitor != $name))\n'
        '                    + [{monitor: $name, path: $path, workspaceFirst: $startWs, workspaceLast: $endWs, thumbnail: $thumb}]\n'
        '                )\' "$SHELL_CONFIG_FILE" > "$SHELL_CONFIG_FILE.tmp" && mv "$SHELL_CONFIG_FILE.tmp" "$SHELL_CONFIG_FILE"\n'
        '        else\n'
        '            jq --arg path "$path" \'.background.wallpaperPath = $path\' "$SHELL_CONFIG_FILE" > "$SHELL_CONFIG_FILE.tmp" && mv "$SHELL_CONFIG_FILE.tmp" "$SHELL_CONFIG_FILE"\n'
        '        fi\n'
        '    fi\n'
        '}\n',
    ),
    (
        "quickshell/ii/scripts/colors/switchwall.sh",
        'kill_existing_mpvpaper() {\n'
        '    pkill -f -9 mpvpaper || true\n'
        '}\n',
        'kill_existing_mpvpaper() {\n'
        '    pkill -f -9 mpvpaper || true\n'
        '}\n'
        '\n'
        'kill_mpvpaper() {\n'
        '    local monitor="${1:-}"\n'
        '    if [ -z "$monitor" ]; then\n'
        '        kill_existing_mpvpaper\n'
        '        return\n'
        '    fi\n'
        '    pkill -f -9 "mpvpaper .* ${monitor}( |$)" || true\n'
        '}\n',
    ),
    (
        "quickshell/ii/scripts/colors/switchwall.sh",
        '    color="$5"\n'
        '\n'
        '    # Start Gemini auto-categorization if enabled\n',
        '    color="$5"\n'
        '    target_monitor="${6:-}"\n'
        '    start_workspace="${7:-}"\n'
        '    end_workspace="${8:-}"\n'
        '\n'
        '    # Start Gemini auto-categorization if enabled\n',
    ),
    (
        "quickshell/ii/scripts/colors/switchwall.sh",
        '        kill_existing_mpvpaper\n'
        '\n'
        '        if is_video "$imgpath"; then\n',
        '        kill_mpvpaper "$target_monitor"\n'
        '\n'
        '        if is_video "$imgpath"; then\n',
    ),
    (
        "quickshell/ii/scripts/colors/switchwall.sh",
        '    switch "$imgpath" "$mode_flag" "$type_flag" "$color_flag" "$color"\n',
        '    switch "$imgpath" "$mode_flag" "$type_flag" "$color_flag" "$color" "$target_monitor" "$start_workspace" "$end_workspace"\n',
    ),
    (
        "quickshell/ii/scripts/colors/switchwall.sh",
        '            --image)\n'
        '                imgpath="$2"\n'
        '                shift 2\n'
        '                ;;\n'
        '            --noswitch)\n'
        '                noswitch_flag="1"\n'
        '                imgpath=$(jq -r \'.background.wallpaperPath\' "$SHELL_CONFIG_FILE" 2>/dev/null || echo "")\n'
        '                shift\n'
        '                ;;\n',
        '            --image)\n'
        '                imgpath="$2"\n'
        '                shift 2\n'
        '                ;;\n'
        '            --monitor)\n'
        '                target_monitor="$2"\n'
        '                shift 2\n'
        '                ;;\n'
        '            --noswitch)\n'
        '                noswitch_flag="1"\n'
        '                if [ -n "$target_monitor" ]; then\n'
        '                    local key\n'
        '                    key=$(frame_wallpaper_key "$target_monitor")\n'
        '                    imgpath=$(jq -r --arg mon "$key" \'(.background.wallpapersByMonitor // [] | map(select(.monitor == $mon)) | .[0].path) // .background.wallpaperPath\' "$SHELL_CONFIG_FILE" 2>/dev/null || echo "")\n'
        '                else\n'
        '                    imgpath=$(jq -r \'.background.wallpaperPath\' "$SHELL_CONFIG_FILE" 2>/dev/null || echo "")\n'
        '                fi\n'
        '                shift\n'
                '                ;;\n',
    ),
    (
        "quickshell/ii/modules/common/widgets/MaterialSymbol.qml",
        "        variableAxes: { \n"
        "            \"FILL\": truncatedFill,\n"
        "            // \"wght\": font.weight,\n"
        "            // \"GRAD\": 0,\n"
        "            \"opsz\": iconSize,\n"
        "        }\n",
        "        // Variable axes drop the ligatures these icon names need.\n",
    ),
)


def install_material_icons(dest: Path) -> list[str]:
    """Icon names are codepoints. Qt on the Frame does not apply the ligatures."""
    src = Path(__file__).resolve().parent / "frame-icons"
    target = dest / "quickshell" / "ii" / "modules" / "common" / "widgets"
    if not src.is_dir() or not target.is_dir():
        return []
    notes = []
    for name in ("MaterialSymbol.qml", "material-glyphs.js"):
        file = src / name
        if file.is_file():
            shutil.copy2(file, target / name)
            notes.append(f"icon {name}")
    return notes


def install_wallpaper_listener(dest: Path) -> list[str]:
    """The per-monitor resolver is ours; the laptop tree does not have it."""
    src = Path(__file__).resolve().parent / "frame-wallpaper" / "WallpaperListener.qml"
    target = dest / "quickshell" / "ii" / "services" / "WallpaperListener.qml"
    if not src.is_file() or not target.parent.is_dir():
        return []
    shutil.copy2(src, target)
    return [f"wallpaper {target.name}"]


def apply_frame_patches(dest: Path) -> list[str]:
    """Correct staged shell bugs without editing the laptop copy."""
    notes = []
    for rel, old, new in SHELL_PATCHES:
        path = dest / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if old not in text or new in text:
            continue
        path.write_text(text.replace(old, new), encoding="utf-8")
        notes.append(f"patch {rel}")
    patch_session_processes(dest)
    return notes


def patch_session_processes(dest: Path) -> None:
    """Scope end-4 process signals to this session, including existing staged copies."""
    # end-4's pkill matches wallpapers in every desktop. The staged shell
    # must only stop clients belonging to its own isolated runtime.
    wall = dest / "quickshell/ii/scripts/colors/switchwall.sh"
    if wall.is_file():
        text = wall.read_text(encoding="utf-8")
        text = text.replace('pkill -f -9 "mpvpaper .* ${monitor}( |$)"',
                            '"$FT_FRAME_SESSION/frame-stop-mpvpaper.py" "$monitor"')
        text = text.replace('pkill -f -9 mpvpaper', '"$FT_FRAME_SESSION/frame-stop-mpvpaper.py"')
        wall.write_text(text, encoding="utf-8")
    terminal_colors = dest / "quickshell/ii/scripts/colors/applycolor.sh"
    if terminal_colors.is_file():
        text = terminal_colors.read_text(encoding="utf-8")
        text = text.replace('kill -SIGUSR1 $(pidof kitty)', '"$FT_FRAME_SESSION/frame-reload-kitty.py"')
        terminal_colors.write_text(text, encoding="utf-8")


def copy_impulse(src: Path, dest: Path) -> list[str]:
    """Shell settings live beside the Quickshell tree, not inside it."""
    notes = []
    dest.mkdir(parents=True, exist_ok=True)
    config = src / "config.json"
    if config.is_file() and not _has_secret(config):
        shutil.copy2(config, dest / "config.json")
    elif config.is_file():
        notes.append(f"skip secret {config}")
    for name in ("actions", "translations"):
        child = src / name
        if child.is_dir():
            notes.extend(copy_tree(child, dest / name))
    return notes


def copy_theme_state(src: Path, dest: Path) -> list[str]:
    """Wallpaper-derived colors and the shell's state files. Not the AI venv."""
    wanted = (
        "states.json",
        "user/first_run.txt",
        "user/generated/colors.json",
        "user/generated/terminal/kitty-theme.conf",
        "user/generated/wallpaper/category.txt",
        "user/generated/wallpaper/path.txt",
    )
    notes = []
    for rel in wanted:
        child = src / rel
        if not child.is_file():
            notes.append(f"missing theme {rel}")
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, target)
    return notes


def font_files_for_families(families: tuple[str, ...] | list[str]) -> list[Path]:
    import subprocess

    found: list[Path] = []
    seen: set[str] = set()
    for family in families:
        try:
            out = subprocess.check_output(["fc-list", family, "file"], text=True)
        except (OSError, subprocess.CalledProcessError):
            continue
        for line in out.splitlines():
            raw = line.split(":", 1)[0].strip()
            if not raw:
                continue
            path = Path(raw)
            if path.name in seen or not path.is_file():
                continue
            seen.add(path.name)
            found.append(path)
    return found


def copy_font_files(files: list[Path], dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    notes = []
    for path in files:
        if path.is_file():
            shutil.copy2(path, dest / path.name)
            notes.append(f"font {path.name}")
    return notes


def stage(hypr: Path, quickshell: Path, dest: Path, replace: bool,
          impulse: Path | None = None, theme_state: Path | None = None,
          wallpaper: Path | None = None, font_files: list[Path] | None = None) -> list[str]:
    if user_config_blocked(dest):
        raise SystemExit(f"frametop: refusing to write a Frame or user config directory: {dest}")
    if dest.exists() and any(dest.iterdir()) and not replace:
        raise SystemExit(f"frametop: stage destination already has files: {dest}")
    if replace and dest.exists() and "/stage/" not in f"{dest}/":
        raise SystemExit(f"frametop: --replace is only for a stage/ directory: {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    notes = []
    notes.extend(copy_tree(hypr, dest / "hypr"))
    notes.extend(copy_tree(quickshell, dest / "quickshell" / "ii"))
    notes.extend(apply_frame_patches(dest))
    notes.extend(install_wallpaper_listener(dest))
    notes.extend(install_material_icons(dest))
    if impulse is not None:
        notes.extend(copy_impulse(impulse, dest / "illogical-impulse"))
    theme = dest.parent / "theme"
    if theme_state is not None:
        notes.extend(copy_theme_state(theme_state, theme / "quickshell"))
    if wallpaper is not None and wallpaper.is_file():
        theme.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wallpaper, theme / "wallpaper.png")
    if font_files:
        notes.extend(copy_font_files(font_files, theme / "fonts"))
    return notes


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] in ("--patch-session-processes", "--prepare-session"):
        dest = Path(argv[1])
        if user_config_blocked(dest):
            raise SystemExit(f"frametop: refusing to patch user config: {dest}")
        if argv[0] == "--prepare-session":
            apply_frame_patches(dest)
            install_wallpaper_listener(dest)
            install_material_icons(dest)
        else:
            patch_session_processes(dest)
        return 0
    parser = argparse.ArgumentParser(description="Stage Hyprland and end-4 configs")
    parser.add_argument("--hypr", type=Path, required=True)
    parser.add_argument("--quickshell", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--impulse", type=Path)
    parser.add_argument("--theme-state", type=Path)
    parser.add_argument("--wallpaper", type=Path)
    parser.add_argument("--fonts", action="store_true")
    args = parser.parse_args(argv)
    fonts = font_files_for_families(FONT_FAMILIES) if args.fonts else None
    notes = stage(
        args.hypr, args.quickshell, args.dest, args.replace,
        impulse=args.impulse, theme_state=args.theme_state,
        wallpaper=args.wallpaper, font_files=fonts,
    )
    for note in notes:
        print(note, file=sys.stderr)
    print(f"staged {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
