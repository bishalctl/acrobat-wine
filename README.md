# Acrobat on Wine

**v26.2.21931 x64 Multilingual · Linux packaging with Wine Staging 11.18**

For experimentation and learning purposes only.

Build a personal AppImage or Nix package from a locally installed Acrobat profile. This repository contains the launchers, Wine compatibility patches, and packaging recipes. The installed application's full version number is `26.002.21931`.

**Only source belongs in Git.** `dist/`, AppImage files, ISO files, `prefix/`, and `packaging/payload/` are covered by [`.gitignore`](.gitignore). Supply private inputs locally and generate the packages yourself. Keep the finished AppImage and all of `dist/` out of commits; the source export excludes them.

## Build locally

Use x86_64 Linux with Nix flakes enabled, Python 3.11 or later, Bash, `zstd`, and `rg` (ripgrep). Before preparing a package, provide these ignored local inputs:

| Input | Location |
| --- | --- |
| A configured installation of the target release — see the [rebuild guide](docs/rebuilding.md) | `prefix/` |
| The matching original ISO [tested using m0nkrus's ISO] | `.local/Acrobat.2026.x64/Adobe.Acrobat.2026.u17.x64.Multilingual.iso` |

`prefix/` is generated locally by Wine and the installer. The [rebuild guide](docs/rebuilding.md) records its structure, required tools, native DLL names and checksums, registry settings, and installation order. GitHub holds that recipe; keep installed files and private backups in your own storage.

With Acrobat closed, run this from the project root to export that installation into the private build payload once:

```sh
./packaging/prepare.sh
```

Skip that step if `packaging/payload/` is already prepared. It exports an existing installation; it does not install Acrobat from the ISO. See [local inputs and preparation](docs/packaging.md#build-from-local-private-inputs) for the requirements and installation-helper limits.

Then build both package formats:

```sh
./packaging/build.sh all
```

For just one format, use `./packaging/build.sh appimage` or `./packaging/build.sh nix`.

| Generated output | Purpose |
| --- | --- |
| `dist/Acrobat-26.002.21931-x86_64.AppImage` | Standalone personal bundle |
| `dist/nix-package` | Link to the built Nix package |
| `dist/flake/` | Prepared local flake with its private payload |
| `dist/SHA256SUMS` | AppImage checksum |

**All of these outputs stay out of Git.** Keep finished bundles and media in private storage. A fresh source checkout has no generated `dist/` bundle to launch.

## Run the build

After the build succeeds, launch the generated AppImage:

```sh
./dist/Acrobat-26.002.21931-x86_64.AppImage
./dist/Acrobat-26.002.21931-x86_64.AppImage /path/to/document.pdf
```

Or run the generated Nix flake:

```sh
nix run path:./dist/flake
nix run path:./dist/flake -- /path/to/document.pdf
```

These commands run the outputs created by `build.sh`; they are not build commands. The AppImage includes Wine, the installed profile seed, compatibility fixes, fonts, and the original ISO. It needs a compatible x86_64 Linux desktop and host graphics drivers. First launch creates a writable per-user profile; later launches reuse it.

For NixOS, use `github:bishalctl/acrobat-wine` as a flake input and [set the AppImage path in your system configuration](docs/packaging.md#use-a-local-appimage-in-nixos). The flake exports `lib.mkAppImagePackage` and `nixosModules.appimage`. Your system repository keeps the downloaded AppImage in an ignored directory. The installed application is independent of this local checkout, which can be removed. A separate source archive, profile archive, or ISO is unnecessary.

## Desktop behavior

- PDFs open in separate document windows by default, reusing the running Acrobat session. Later changes to the tab preference remain yours.
- Ordinary Open/Browse dialogs use the Linux desktop's file-picker portal, with Wine as a fallback. Save As and specialized dialogs retain Wine's implementation.
- On Hyprland, the application uses XWayland. Small Acrobat tips remain popups; window placement and focus follow your desktop settings.
- Closing the last application window returns control to the terminal. Ctrl+C stops that launch and its remaining Adobe helpers.
- The launching user's home and filesystem are available through `H:` and `Z:`, subject to Unix permissions.
- Automatic updates are disabled for this release. GPU acceleration remains enabled; hardware compatibility has not been established on every system.
- Normal launches log to `journalctl --user -t acrobat-wine -b` and rotating files.
- The NixOS launcher caches successful AppImage verification until the file changes, avoiding a full-image read for every PDF opened.

See [packaging and private backups](docs/packaging.md) for AppImage recovery, NixOS integration, profiles, and build commands; [rebuilding the prefix](docs/rebuilding.md) for installation inputs and structure; and [compatibility and validation](docs/compatibility.md) for the patches and known limits.

## Source layout

| Path | Purpose |
| --- | --- |
| `flake.nix`, `flake.lock` | Pinned Nix build and checks |
| `modules/acrobat-appimage.nix` | NixOS integration for a downloaded local AppImage |
| `packaging/appimage-package.nix` | Package constructor with a caller-supplied AppImage path |
| `packaging/` | Launchers, AppImage assembly, profile/source exporters, and tests |
| `scripts/`, `config/` | Local installation helpers and compatibility settings |
| `docs/` | Packaging and compatibility guides |

Local media and tools live in `.local/`; the working Wine profile is `prefix/`. Generated packages go into `dist/`, and local diagnostics go into `state/` and `logs/`. All of these are ignored.

## Check and export source

These commands work without the private installation or ISO:

```sh
./packaging/build.sh check
python3 packaging/source_tree.py --check
python3 packaging/source_tree.py --output dist/github-source
```

The source exporter uses an explicit file list, rejects binaries, symlinks, and common credential patterns, and refuses to overwrite an existing export. Review the exported files before uploading them. A clean export contains no Git metadata or history.

`.gitignore` does not remove files already tracked or committed. If reusing an existing Git repository, review its index and history separately; a new repository created from the source export avoids carrying old history into the upload. Keep finished bundles and personal media in private storage.

This is an independent experiment, not an official Adobe project. Adobe's application and trademarks, Wine, and bundled third-party components retain their respective ownership and licenses.
