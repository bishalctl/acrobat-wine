# Packaging Acrobat on Wine

Target: **v26.2.21931 x64 Multilingual** (`26.002.21931` internally), with **Wine Staging 11.18**. For experimentation and learning purposes only.

## Build from local private inputs

The repository contains source code and recipes. The ISO, installed profile, private payload, and every output under `dist/` are ignored local files; none are supplied by a source checkout or included in the source export.

To package an existing installation, supply these local inputs:

- The configured Wine profile at `prefix/`, containing the target application version.
- The original ISO at `.local/Acrobat.2026.x64/Adobe.Acrobat.2026.u17.x64.Multilingual.iso`.
- Nix with flakes enabled, Python 3.11 or later, `zstd`, Bash, and standard build utilities. Source auditing uses `rg` (ripgrep).

With Acrobat closed, run this from the project root to create the private seed once, or intentionally refresh it after changing your installation:

```sh
./packaging/prepare.sh
```

The exporter verifies the installed executable, excludes documents, browser caches/cookies, diagnostics, recent-file/session history, and external symlinks, then writes `packaging/payload/`. The installed application and its settings remain private even after this cleanup. The helper verifies and includes the original ISO. Existing media may share hard links with staged builds; never edit those files in place.

If `packaging/payload/` is already prepared, skip preparation. Build from that seed:

```sh
./packaging/build.sh all       # Nix package and AppImage
./packaging/build.sh nix       # Nix package only
./packaging/build.sh appimage  # AppImage only
./packaging/build.sh check    # Source checks; no private payload needed
```

`build.sh all` creates `dist/nix-package`, `dist/Acrobat-26.002.21931-x86_64.AppImage`, `dist/SHA256SUMS`, and the private `dist/flake`. **Do not commit these outputs or force-add the ignored payload/media.** Checks use a separate source-only stage and do not replace the prepared private flake. Nix cache/config files stay under `state/`.

Preparation requires an installed profile; an ISO alone is insufficient. The local `setup.sh` and `scripts/` utilities document the original installation workflow and expect its tools in `.local/bin/`; they are not a complete bootstrap for a fresh machine. The package build consumes the prepared installation rather than changing its activation setup.

## Run and back up the AppImage

After building it locally, run the generated file:

```sh
./dist/Acrobat-26.002.21931-x86_64.AppImage
./dist/Acrobat-26.002.21931-x86_64.AppImage /path/to/document.pdf
```

You can keep the completed AppImage and `dist/SHA256SUMS` in private storage such as Google Drive. Download both into the same directory, verify the bytes, and restore executable permission:

```sh
sha256sum --check SHA256SUMS
chmod +x Acrobat-26.002.21931-x86_64.AppImage
./Acrobat-26.002.21931-x86_64.AppImage
```

The built AppImage contains the installation seed, Wine/runtime libraries, compatibility fixes, fonts, and original ISO. It does not need this repository or a separate ISO at launch. It still needs a compatible x86_64 Linux desktop, host display/graphics drivers, and sufficient free space. Uploading the original AppImage does not back up subsequent changes to your writable profile or documents; back those up separately while the application is closed.

If FUSE is unavailable:

```sh
APPIMAGE_EXTRACT_AND_RUN=1 ./Acrobat-26.002.21931-x86_64.AppImage
```

Extraction requires additional temporary disk space. If the matching runtime is absent from the host's Nix store, the embedded launcher needs unprivileged user/mount namespaces. It makes a private filesystem view that preserves host files and graphics-driver paths alongside the bundled runtime.

To recover the original ISO into an existing directory:

```sh
./Acrobat-26.002.21931-x86_64.AppImage --extract-iso /path/to/recovery/
```

Extraction refuses to overwrite an existing file. The expected media is `Adobe.Acrobat.2026.u17.x64.Multilingual.iso`, SHA-1 `a839dfadeb73ed050721f40efd2d338cda3b4f76`. Recovery does not reinstall or update the application.

## Use a local AppImage in NixOS

The system flake fetches the packaging code from GitHub. Your system configuration supplies the path to a downloaded AppImage, kept in an ignored local directory. The local checkout of this packaging repository can be removed; neither building the launcher nor running the application depends on it. The AppImage already contains the installed seed, Wine runtime, fonts, fixes, and ISO; no separate `.tar.gz` or profile archive is needed.

Add the source repository to your system flake's inputs:

```nix
inputs.acrobat.url = "github:bishalctl/acrobat-wine";
```

Use the exported package constructor in a NixOS configuration module. Pass your flake inputs through `specialArgs = { inherit inputs; };` if they are not already available there:

```nix
{ inputs, pkgs, ... }:
{
  environment.systemPackages = [
    (inputs.acrobat.lib.mkAppImagePackage {
      inherit pkgs;
      appImage = "/etc/nixos/local/acrobat/Acrobat.AppImage";
      # Optional: sha256 = "<64 lowercase hex characters from SHA256SUMS>";
    })
  ];
}
```

`appImage` is required and has no default. Choose the filename and location in your system configuration, and place the executable, verified AppImage there. Keep it a **quoted absolute string**: the launcher opens that path at runtime. This allows the binary to stay outside the Git flake's source snapshot and Nix store, and allows system rebuilds before downloading it. See the [Nix flake reference](https://nix.dev/manual/nix/2.35/command-ref/new-cli/nix3-flake#path-like-syntax).

For the example path above, the system repository's `.gitignore` should contain:

```gitignore
/local/acrobat/
*.[aA][pP][pP][iI][mM][aA][gG][eE]
```

The equivalent module interface is also available through the same GitHub input:

```nix
{ inputs, ... }:
{
  imports = [ inputs.acrobat.nixosModules.appimage ];
  programs.acrobat-appimage = {
    enable = true;
    appImage = "/etc/nixos/local/acrobat/Acrobat.AppImage";
  };
}
```

Use either interface to install the `acrobat-wine` command and **Acrobat (Wine)** desktop entry. Both use the bundle's own launcher, so window placement, file picking, profiles, shutdown, and journal logging retain the AppImage's behavior. The default PDF application is unchanged. If the file is missing or lacks executable permission, the launcher explains how to restore it. With `sha256` set, it verifies the image on every launch; a replacement bundle needs its new checksum in the configuration.

On another machine, restore the system configuration and download the same AppImage to that path. No rebuild is needed just to restore the file. Keep the AppImage available at its configured location; Nix generations do not contain a backup of it. Later writable profile changes still need their own backup.

The GitHub input supplies the packaging code; the configured external path supplies the application. Neither interface requires this project's private build payload or a system Wine installation.

## Native Nix package

For a prepared private flake:

```sh
nix run path:./dist/flake
nix run path:./dist/flake -- /path/to/document.pdf
nix run path:./dist/flake -- --version
```

`dist/flake` contains a small build tree and the private payload. `path:` explicitly selects the directory contents. In a Git checkout, plain `nix run .` uses the Git source view and omits the ignored payload, so it cannot launch the private application. A source-only checkout exposes the Wine/runtime build outputs and tests; application outputs become available when the payload is present. If you copy the prepared flake into its own directory outside a Git checkout, you can `cd` there and use `nix run` directly.

Using `path:.` on the working project root would import local profiles, logs, and build output too. Use the staged flake to avoid that large copy. Preserve `dist/flake` as a real directory when moving it:

```sh
cp -aL dist/flake /destination/acrobat-private-flake
```

The prepared private flake is a build output for local testing. Use the GitHub input and configurable AppImage package above for system integration. Wine and Acrobat versions are supplied by the AppImage independently of your system Wine.

## Profiles, file dialogs, and logs

First launch verifies and expands the prepared installation into a writable profile, requiring about 4.5 GB of additional space. The package reuses that profile on later launches.

| Content | Default location |
| --- | --- |
| Wine profile | `~/.local/share/acrobat-wine/prefix` |
| Version record | `~/.local/share/acrobat-wine/profile.json` |
| Rotating logs | `~/.local/state/acrobat-wine/logs/acrobat.log` |

These paths follow `XDG_DATA_HOME` and `XDG_STATE_HOME`. `ACROBAT_DATA_HOME` and `ACROBAT_STATE_HOME` override the complete application directories, which is useful for disposable tests. The project launcher `./acrobat` uses its separate local `prefix/`.

`H:` maps to the launching user's home and `Z:` maps to `/`. Existing nonempty Windows document folders are preserved. The mappings do not bypass Unix permissions. Absolute Linux paths and local `file://` URLs can be passed to the launcher.

Ordinary Open/Browse dialogs use the host's configured `xdg-desktop-portal` FileChooser backend. The desktop decides which picker appears; it is not a separately launched file-manager window. Save As, specialized dialogs, and systems without a working portal use Wine dialogs. Set `ACROBAT_NATIVE_FILE_CHOOSER=0` to disable the bridge. After replacing a bundle, close its existing application windows before relaunching to load the new runtime.

Closing the last window preserves save prompts, then returns control to the terminal and cleans up that launch's remaining Adobe helpers. Ctrl+C also stops the launch, escalating if Wine ignores the interrupt. Independent launches and shared Wine servers are preserved.

```sh
journalctl --user -t acrobat-wine -b
journalctl --user -t acrobat-wine -f
```

The journal records startup, Wine output, relevant process/graphics information, exceptions, and exit status. Rotating file logs also work without journald. `--diagnostics` prints resolved paths and graphics availability without starting Wine. Treat diagnostic output as private: it can contain filenames and host information.

## Prepare a GitHub upload

Keep the ISO, finished bundles, and working profile in private storage. Only upload reviewed source:

```sh
python3 packaging/source_tree.py --check
python3 packaging/source_tree.py --output dist/github-source
```

The explicit list in `packaging/source-files.txt` defines the export. Auditing checks the visible working tree, the Git index when accessible, and the listed file contents. It rejects unexpected files, binaries, symlinks, local home paths, and common credential patterns. It does not inspect Git history or certify that every possible secret has been found. Review the export before creating a fresh repository from it.

Ignoring a file does not untrack an existing commit. If preserving an old repository, inspect and clean its tracked files and history before pushing. The exported directory contains no `.git` metadata, payload, application icon extracted from Adobe, or local test records. The source icon is an original generic document drawing.
