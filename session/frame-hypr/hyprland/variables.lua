-- The laptop variables name programs under ~/.config/hypr. That directory
-- is the laptop's, so the Frame session launches the same apps directly.
local root = os.getenv("FT_HYPR_CONFIG_ROOT") or ""
dofile(root .. "/hyprland/variables.lua")
-- Other laptop app shortcuts use the same staged launch helper.
local function staged(command)
    return command:gsub("~/%.config/hypr", function() return root end)
end
codeEditor = staged(codeEditor)
officeSoftware = staged(officeSoftware)
textEditor = staged(textEditor)
volumeMixer = staged(volumeMixer)
taskManager = staged(taskManager)
local session = os.getenv("FT_FRAME_SESSION") or ""
local launch = session .. "/frame-app.sh"
terminal = launch .. " terminal"
fileManager = launch .. " files"
browser = launch .. " browser"
local stage = os.getenv("FT_USER_CONFIG_HOME") or ""
settingsApp = "qs -p " .. stage .. "/quickshell/ii/settings.qml"
