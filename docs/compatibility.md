# Acrobat on Wine compatibility

This experiment targets **v26.2.21931 x64 Multilingual**, whose executable reports **26.002.21931**, with **Wine Staging 11.18**. For experimentation and learning purposes only. The build pins Nixpkgs and the AppImage tooling in `flake.lock`.

## Included changes

| Area | Implementation |
| --- | --- |
| Certificate-store lifetime | A Wine `crypt32` patch addresses the observed forced-close handling. |
| Task termination | The local installation retains the existing `EndTask` compatibility shim and native Rich Edit DLLs. |
| Open/Browse dialogs | A Wine `comdlg32` bridge calls the Linux FileChooser portal through a local D-Bus broker. Unicode paths, PDF filters, multiple selection, and cancellation are supported. Unsupported dialogs fall back to Wine. |
| Small in-app tips | A narrowly scoped Wine X11 patch keeps owned, borderless, layered `AVL_AVWindow` tips as popups. Ordinary application windows, dialogs, and tool palettes retain normal handling. |
| Fonts and appearance | The private seed preserves its configured Selawik/Adobe fonts and classic dark interface. Fonts are not included in Git. |
| Filesystem access | `H:` and `Z:` expose home and `/` with the launching user's permissions. |
| Process lifetime | The supervisor follows this launch's Acrobat processes, handles detached restarts, and stops leftover Adobe helpers on close or terminal interruption. |
| Diagnostics | Normal launches emit journal records and rotating logs, including relevant crash and graphics/process details. Exit status 1 alone is not classified as a crash. |
| Release pinning | Updater policies and disabled updater helpers preserve the installed release. GPU acceleration remains enabled. |

Patch sources are in [`scripts/wine-compat/`](../scripts/wine-compat/); the packaged runtime is assembled by [`packaging/wine-runtime.nix`](../packaging/wine-runtime.nix). Windows executable names, registry keys, and Adobe API identifiers retain their required original names.

## Display and desktop behavior

On Hyprland, the packaged application uses **XWayland**, through Wine's X11 driver. The native file picker is a separate desktop portal component. The package leaves workspace placement, activation, and tiling to the desktop. The local `ACROBAT_TEST_WORKSPACE=4` option is exclusively a testing aid and is not installed by the packages.

## Validation

The prepared personal bundle was tested with a separate profile and private X display. Verification covered:

- Fresh profile creation, executable/DLL integrity, fonts, updater restrictions, and enabled GPU settings.
- PDF rendering, text editing, saving and reopening, and independent extraction of the saved text.
- External filenames with spaces, an accent, and `%`; home/root browsing and mappings.
- Native Open selection, cancellation, multiple files, and the retained Wine Save As dialog.
- Popup classification against eleven real Wine window shapes, including the reported blue Acrobat tip and a regular document dialog.
- Normal window close, terminal interrupts, detached helper cleanup, and document forwarding to an existing instance.
- Embedded AppImage namespace/runtime use, journal startup/exit records, and recovery of the unchanged ISO.

The automated launcher tests run with `./packaging/build.sh check`; they do not need the private payload. They exercise launch ownership and shutdown, profile/export behavior, and a simulated D-Bus portal. The optional [`popup_windows.py`](../packaging/tests/popup_windows.py) probe needs Windows Python and a private X display. Local screenshots, logs, host details, and session records are intentionally excluded from the repository.

## Known limits

Hardware GPU acceleration and cross-machine graphics stability were not proven by the sandbox tests. The settings remain enabled, but the test environment had no GPU devices. An earlier intermittent CEF startup crash is not established as fixed. OCR, printing, and cloud services remain untested.

The test environment also lacked `/dev/fuse`; AppImage extraction mode and the embedded runtime were verified instead. Host graphics drivers, desktop portal configuration, and namespace permissions can affect portability. See [packaging](packaging.md) for runtime requirements and logs.

## Upstream components

The project uses [Wine](https://www.winehq.org/), [Nixpkgs](https://github.com/NixOS/nixpkgs), [nix-appimage](https://github.com/ralismark/nix-appimage), the [AppImage type-2 runtime](https://github.com/AppImage/type2-runtime), the desktop [FileChooser portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.FileChooser.html), and the [systemd native journal protocol](https://systemd.io/JOURNAL_NATIVE_PROTOCOL/). The retained Selawik license is in [`packaging/Selawik-LICENSE.txt`](../packaging/Selawik-LICENSE.txt). Component licenses and ownership are unchanged by this experiment.
