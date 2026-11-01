#!/usr/bin/env bash
# Point the staged end-4 shell at its colors, wallpaper, and fonts.
# Writes the stage copy, this session's state, and the session's app theme.
# It does not write ~/.config or ~/.local/share.
set -eu
here=$(dirname "$(readlink -f "$0")")
config_home=${1:-${FT_USER_CONFIG_HOME:-$HOME/.config}}
theme=$(readlink -f "$config_home/../theme" 2>/dev/null || true)
state_root=${XDG_STATE_HOME:-$HOME/.local/state}
qs_state=$state_root/quickshell
if [ -n "${theme:-}" ] && [ -d "$theme/quickshell" ] && [ ! -f "$qs_state/user/generated/colors.json" ]; then
  mkdir -p "$qs_state"
  cp -a "$theme/quickshell/." "$qs_state/"
fi
wall=${theme:-}/wallpaper.png
if [ -n "${theme:-}" ] && [ -f "$wall" ]; then
  python3 - "$config_home/illogical-impulse/config.json" "$qs_state/user/generated/wallpaper/path.txt" "$wall" <<'PY'
import json
import pathlib
import sys

cfg, path_txt, wall = map(pathlib.Path, sys.argv[1:])
selected = None
if cfg.is_file():
    data = json.loads(cfg.read_text(encoding="utf-8"))
    background = data.setdefault("background", {})
    current = background.get("wallpaperPath")
    if isinstance(current, str) and pathlib.Path(current).is_file():
        selected = pathlib.Path(current)
    else:
        background["wallpaperPath"] = str(wall)
        selected = wall
        cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
path_txt.parent.mkdir(parents=True, exist_ok=True)
if not path_txt.is_file() or not pathlib.Path(path_txt.read_text(encoding="utf-8").strip()).is_file():
    path_txt.write_text(str(selected or wall) + "\n", encoding="utf-8")
PY
fi
# Resolve the laptop's default volume mixer to the container application.
# Preserve a command the user has chosen in the shell settings.
python3 - "$config_home/illogical-impulse/config.json" <<'PYCONFIG'
import json
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
    apps = data.get("apps", {})
    if apps.get("volumeMixer", "").startswith("~/.config/hypr/hyprland/scripts/launch_first_available.sh"):
        apps["volumeMixer"] = "pavucontrol"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
except (ValueError, OSError, AttributeError):
    pass
PYCONFIG
gtk=$config_home/gtk-3.0
mkdir -p "$gtk"
if [ ! -f "$gtk/settings.ini" ]; then
  printf '%s\n' '[Settings]' 'gtk-icon-theme-name=breeze' >"$gtk/settings.ini"
fi
app_config=${FT_APP_CONFIG_HOME:-$HOME/.config/frametop/hyprland}
app_data=${FT_APP_DATA_HOME:-$HOME/.local/share/frametop/hyprland}
colors=$qs_state/user/generated/colors.json
if [ ! -f "$colors" ] && [ -n "${theme:-}" ] && [ -f "$theme/quickshell/user/generated/colors.json" ]; then
  colors=$theme/quickshell/user/generated/colors.json
fi
if [ -f "$colors" ]; then
  python3 "$here/frame-kde-theme.py" "$colors" "$app_config" "$app_data"
fi
# Seed the laptop-style Kitty setup once, leaving later edits intact.
mkdir -p "$app_config/kitty"
if [ ! -f "$app_config/kitty/kitty.conf" ]; then
  cp "$here/kitty.conf" "$app_config/kitty/kitty.conf"
fi
if [ ! -f "$app_config/kitty/search.py" ]; then
  cp "$here/fish/kitty-search.py" "$app_config/kitty/search.py"
fi
mkdir -p "$app_config/fish"
if [ ! -f "$app_config/fish/config.fish" ]; then
  cp "$here/fish/config.fish" "$app_config/fish/config.fish"
fi
if [ ! -f "$app_config/starship.toml" ]; then
  cp "$here/fish/starship.toml" "$app_config/starship.toml"
fi
if [ -n "${theme:-}" ] && [ -d "$theme/fonts" ]; then
  conf=${XDG_RUNTIME_DIR:-/tmp}/frametop-fonts.conf
  cat >"$conf" <<EOF
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>
  <dir>$theme/fonts</dir>
</fontconfig>
EOF
  printf 'FONTCONFIG_FILE=%q\n' "$conf"
  # A variable Material Symbols file drops its icon ligatures in this Qt.
  # The static instance is one weight and one optical size, and the names resolve.
  static=$here/MaterialSymbolsRounded-static.ttf
  material=$(printf '%s\n' "$theme/fonts"/MaterialSymbolsRounded*.ttf | head -1)
  if [ -f "$static" ]; then
    material=$static
  fi
  if [ -f "$material" ]; then
    plain=${XDG_RUNTIME_DIR:-/tmp}/MaterialSymbolsRounded.ttf
    ln -sfn "$material" "$plain"
    printf 'FT_FRAME_FONT_MATERIAL=%q\n' "$plain"
  fi
fi
