-- Local inspection only: enabled explicitly with ACROBAT_TEST_WORKSPACE=4.
-- This file is not shipped in the AppImage or Nix package.
hl.window_rule({
    -- Keep Acrobat and its dialogs on workspace 4 without taking keyboard focus.
    name = "acrobat-wine-workspace-4",
    match = {
        class = "^(acrobat[.]exe|acrotray[.]exe|adobecollabsync[.]exe|acrocef[.]exe|adobe_licensing_wf_acro[.]exe|adobe_licensing_wf_helper_acro[.]exe|autoplay[.]exe|crack[.]exe|setup[.]exe|msiexec[.]exe|wineboot[.]exe|winecfg[.]exe|winedbg[.]exe|vcredist_x64[.]exe|vcredist_x86[.]exe|vc_redist[.]x64[.]exe|vc_redist[.]x86[.]exe)$"
    },
    workspace = "4 silent",
    no_initial_focus = true,
    suppress_event = "activate activatefocus"
})

-- Only document windows tile; small prompts retain their dialog geometry.
hl.window_rule({
    name = "acrobat-wine-document-tile",
    match = { class = "^acrobat[.]exe$", title = "^.*Adobe Acrobat( Pro)? [(]64-bit[)]$" },
    tile = true,
    scrolling_width = 1.0
})

hl.window_rule({
    name = "acrobat-wine-debugger-workspace-4",
    match = { class = "^conhost[.]exe$", title = "^Wine Debugger$" },
    workspace = "4 silent",
    no_initial_focus = true,
    suppress_event = "activate activatefocus"
})

-- Some Wine dialogs request another workspace after their initial mapping.
-- Reapply the destination without activating the window or its workspace.
_G.acrobat_wine_workspace_classes = {
        ["acrobat.exe"] = true,
        ["acrotray.exe"] = true,
        ["adobecollabsync.exe"] = true,
        ["acrocef.exe"] = true,
        ["adobe_licensing_wf_acro.exe"] = true,
        ["adobe_licensing_wf_helper_acro.exe"] = true,
        ["autoplay.exe"] = true,
        ["crack.exe"] = true,
        ["setup.exe"] = true,
        ["msiexec.exe"] = true,
        ["wineboot.exe"] = true,
        ["winecfg.exe"] = true,
        ["winedbg.exe"] = true,
        ["vcredist_x64.exe"] = true,
        ["vcredist_x86.exe"] = true,
        ["vc_redist.x64.exe"] = true,
        ["vc_redist.x86.exe"] = true
}
if not _G.acrobat_wine_workspace_guard_v2 then
    _G.acrobat_wine_workspace_guard_v2 = function()
        for _, window in ipairs(hl.get_windows()) do
            if _G.acrobat_wine_workspace_classes[string.lower(window.class)] and window.mapped
                    and window.workspace and window.workspace.id ~= 4 then
                hl.dispatch(hl.dsp.window.move({
                    workspace = "4", window = "address:" .. window.address,
                    follow = false
                }))
            end
        end
    end
    for _, event in ipairs({ "window.open", "window.title", "window.move_to_workspace" }) do
        hl.on(event, _G.acrobat_wine_workspace_guard_v2)
    end
end
_G.acrobat_wine_workspace_guard_v2()
