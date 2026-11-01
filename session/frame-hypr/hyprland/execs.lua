-- Frame startup. Replaces hyprland.execs from the laptop config via package.path
-- so that file stays untouched. No hypridle, brightness keys, geoclue agent,
-- or easyeffects. Quickshell is a separate process: if it exits, Hyprland stays.
hl.on("hyprland.start", function()
    local root = os.getenv("FT_FRAME_SESSION")
    local runtime = os.getenv("XDG_RUNTIME_DIR")
    if root and #root > 0 then
        hl.exec_cmd(root .. "/frame-quickshell.sh")
        if os.getenv("FT_NO_VR_SMOKE") then
            local count = tonumber(os.getenv("FT_SCREEN_COUNT") or "1") or 1
            for _ = 2, count do
                hl.exec_cmd("hyprctl output create wayland")
            end
            return
        end
        hl.exec_cmd(root .. "/frame-shell-services.sh")
        -- Controller chords talk to this process. Quickshell failing does not
        -- stop it, and this process exiting does not stop Hyprland.
        if runtime and #runtime > 0 then
            hl.exec_cmd("python3 " .. root .. "/frame-desktopd.py " .. runtime .. "/frametop-desktop.sock")
        end
        -- Claims Hyprland monitors onto Frametop slots. If it exits, the
        -- panels stay on whatever slots they already have.
        hl.exec_cmd("python3 " .. root .. "/hyprland_outputs.py")
    end
end)
