-- Load end-4's helpers, but resolve its optional custom-file checks against
-- the staged tree. The host's ~/.config/hypr belongs to another desktop.
local root = assert(os.getenv("FT_HYPR_CONFIG_ROOT"), "missing staged Hyprland configuration")
dofile(root .. "/hyprland/lib/init.lua")
local original = is_file_exists
function is_file_exists(path)
    local home = os.getenv("HOME") or ""
    local prefix = home .. "/.config/hypr/"
    if path:sub(1, #prefix) == prefix then
        path = root .. "/" .. path:sub(#prefix + 1)
    end
    return original(path)
end
