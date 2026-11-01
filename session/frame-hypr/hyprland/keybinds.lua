-- end-4's bindings refer to ~/.config even though this session runs a staged
-- copy. Resolve those script paths without changing either user's config.
local root = assert(os.getenv("FT_HYPR_CONFIG_ROOT"), "missing staged Hyprland configuration")
local path = root .. "/hyprland/keybinds.lua"
local file = assert(io.open(path, "r"))
local source = file:read("*a")
file:close()
source = source:gsub("%$HOME/%.config/hypr/hyprland/scripts", "${FT_HYPR_CONFIG_ROOT}/hyprland/scripts")
source = source:gsub("%$HOME/%.config/quickshell/%$qsConfig", "${FT_USER_CONFIG_HOME}/quickshell/$qsConfig")
local chunk, err = load(source, "@" .. path)
assert(chunk, err)()
