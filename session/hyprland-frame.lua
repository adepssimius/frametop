-- Frame entry. Loads the laptop Hyprland config when it is present, with
-- session/frame-hypr ahead of it on package.path. The laptop files are not written.
local home = os.getenv("HOME") or ""
local source = debug.getinfo(1, "S").source
local here = source:sub(1, 1) == "@" and source:sub(2):match("(.*/)") or "./"
local override = here .. "frame-hypr"
local user = os.getenv("FT_HYPR_CONFIG_ROOT")
if not user or user == "" then user = home .. "/.config/hypr" end
package.path = override .. "/?.lua;" .. override .. "/?/init.lua;"
    .. user .. "/?.lua;" .. user .. "/?/init.lua;" .. package.path

local user_entry = user .. "/hyprland.lua"
local user_file = io.open(user_entry, "r")
if user_file then
    user_file:close()
    dofile(user_entry)
else
    hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1 })
    hl.config({
        general = { gaps_in = 0, gaps_out = 0, border_size = 1 },
        misc = { force_default_wallpaper = 0, disable_hyprland_logo = true },
    })
    hl.on("hyprland.start", function()
        local startup = os.getenv("FT_HYPRLAND_STARTUP")
        if startup and #startup > 0 then hl.exec_cmd(startup) end
    end)
    hl.bind("SUPER + Return", hl.dsp.exec_cmd("sh -c 'if command -v foot >/dev/null; then exec foot; elif command -v kitty >/dev/null; then exec kitty; fi'"))
    hl.bind("SUPER + SHIFT + E", hl.dsp.exec_cmd("hyprctl dispatch exit"))
end
-- Same as Plasma's KWin shortcuts: Hide/Show Screens and Reset Screen Layout.
do
    local session = os.getenv("FT_FRAME_SESSION") or here
    hl.bind("SUPER + SHIFT + H", hl.dsp.exec_cmd(session .. "/../layout/ft-hide-show"))
    hl.bind("SUPER + SHIFT + R", hl.dsp.exec_cmd(session .. "/../layout/ft-layout-reset"))
end
-- The laptop config draws for a denser panel (scale 1.25). This screen is the
-- Frame panel, so the shell uses the panel's own pixels.
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1 })
