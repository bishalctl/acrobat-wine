# Rebuilding the Wine prefix

This is the source-only reconstruction recipe for **Acrobat v26.2.21931 x64 Multilingual** (`26.002.21931`) on **Wine Staging 11.18**. A prefix is created by Wine, populated by the installer, and configured by the scripts in this repository. Its binaries, registry exports, and user data stay outside Git.

The original installation and packaged application were tested. The tool bundle and DLL references below are checked independently; the complete installation sequence has not yet been repeated from an empty checkout with this tool bundle. The installer still requires interaction. Recreating the same release and settings does not promise a byte-identical copy of an existing user's prefix.

## External inputs

| Input | Required identity and local destination |
| --- | --- |
| Original media | The tested ISO referenced in [README](../README.md), stored at `.local/Acrobat.2026.x64/Adobe.Acrobat.2026.u17.x64.Multilingual.iso`; SHA-1 `a839dfadeb73ed050721f40efd2d338cda3b4f76` |
| Windows Python | Python.org's `python-3.11.9-embed-amd64.zip`, extracted into `.local/python-windows/`; SHA-256 `009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b` |
| Native Microsoft DLLs | Exact x64/x86 files listed below; the helper downloads them from Microsoft's symbol server and verifies SHA-256 |
| Fonts | Winetricks `corefonts` and `tahoma`, Selawik 1.01, and Adobe fonts from the local installation |

The ISO-specific compatibility transform also requires these extracted originals under `.local/installer/Adobe Acrobat/`:

```text
AcroPro.msi
  SHA-256 089dc9a23f5eb868a6f6b8a6a901c2a29faef113ad296c8d40f6ce9de60f4b2d
AcrobatDCx64Upd2600221931.msp
  SHA-256 7f8f1e7fe86a0282e773d3cfca8cfc17293a444226f9a653938b7de671d9c9fb
```

Other ISOs or updates may require different transforms. The helpers reject inputs whose pinned checksums differ. Supply application media and installation state yourself; none is downloaded from or published in this repository.

## Set up the tools in a fresh checkout

Use a separate checkout for a new installation. `setup.sh` works on that checkout's `prefix/`; it is not a disposable-profile test command for an existing installation.

With Nix flakes, Git, and Bash available, run from the fresh source checkout:

```sh
mkdir -p .local/bin .local/downloads .local/python-windows state/cache state/config
export XDG_CACHE_HOME="$PWD/state/cache"
export XDG_CONFIG_HOME="$PWD/state/config"
nix build .#setup-tools --out-link .local/setup-tools
export PATH="$PWD/.local/setup-tools/bin:$PATH"

for tool in wine wineboot winecfg wineserver winepath winedbg \
  winetricks 7z cabextract x86_64-w64-mingw32-gcc; do
  ln -s "../setup-tools/bin/$tool" ".local/bin/$tool"
done
```

The package in [setup-tools.nix](../packaging/setup-tools.nix) takes its tools from the revision in `flake.lock`: Wine Staging 11.18, Winetricks 20260125, p7zip 17.06, cabextract 1.11, the x64 MinGW compiler, and supporting Linux utilities. The writable `.local/bin/` directory is intentional: installation replaces its Wine links with the patched local runtime. The commands above expect those links not to exist already.

Place the Windows Python archive in `.local/downloads/`, then verify and extract it:

```sh
printf '%s  %s\n' \
  009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b \
  .local/downloads/python-3.11.9-embed-amd64.zip | sha256sum --check && \
  unzip .local/downloads/python-3.11.9-embed-amd64.zip -d .local/python-windows
```

This Windows Python is an installation/diagnostic tool used by the existing helpers. Normal packaged launches use the runtime provided by the bundle.

## Install and configure

Place the ISO at the path above, then use the normal interactive setup workflow:

```sh
./setup.sh --prepare-only
./setup.sh
# Complete and close the ISO's installer before continuing.
./setup.sh --finish
python3 scripts/version.py
```

The last command must report `26.002.21931`. Setup checks the ISO before extraction. It creates a `win64` prefix with Windows 10 compatibility, installs the font prerequisites and native DLLs, builds the Wine compatibility components, and applies the registry templates. It refuses to update an already installed Acrobat through this workflow.

Before starting the installer, [prepare-update.py](../scripts/prepare-update.py) corrects the update's `Media[DiskId=6].LastSequence` from `12104` to `6406` in a separate MSP copy. [prepare-iso-runtime.py](../scripts/prepare-iso-runtime.py) removes only the synthetic Wine `msvcp140.dll` copies that the ISO is supposed to replace, after verifying the file marker and MSI directory mapping. Neither operation edits the ISO.

The finish step verifies the installed application and the supplied installer workflow, repairs the Rich Edit control, registers fonts, applies the final appearance settings, and disables update helpers/services/tasks. Keep the installer choices consistent with the target release. Select the dark appearance in Acrobat if desired; personal UI choices are not a substitute for the registry/configuration steps below.

Validate opening, editing, saving, shutdown, and update/GPU settings before exporting a newly created installation. Close Acrobat before packaging:

```sh
./packaging/prepare.sh
./packaging/build.sh all
```

For an already prepared private payload, skip `prepare.sh` and build directly. See [private backups](packaging.md#what-to-keep-in-private-storage).

## Prefix structure

This is a structural reference, with the user name replaced by a placeholder. It is not an export of a user's files or registry values.

```text
prefix/
  system.reg                         # machine registry generated by Wine/installers
  user.reg                           # user registry and application preferences
  userdef.reg                        # default-user registry
  dosdevices/                        # drive links rebuilt for the launching user
  drive_c/
    Program Files/Adobe/Acrobat DC/
      Acrobat/                       # Acrobat.exe, installed DLLs, plugins, resources
      Resource/                      # installed fonts and other Adobe resources
    Program Files (x86)/             # installer-provided 32-bit components, if present
    ProgramData/                     # installation/application data
    windows/
      system32/                      # x64 libraries in this win64 prefix
      syswow64/                      # x86 libraries
      Fonts/                         # locally installed/registered fonts
    users/<windows-user>/
      AppData/                       # user-specific application state
      Desktop/ Documents/ Downloads/ # user files, excluded from the packaged seed
```

Wine and the supplied installer generate the base files. Custom compatibility files are listed next. The exporter excludes documents, browser/session caches, temporary diagnostics, recent-file history, and external symlinks. The packaged launcher creates per-user `C:`, `H:` and `Z:` links; do not copy another user's drive links or registry dumps as a public template.

## Installer-provided files

The ISO supplies `Acrobat.exe`, the application's other DLLs/plugins/resources, and its Visual C++ runtime files. [finish-install.sh](../scripts/finish-install.sh) also checks the app-local `version.dll` and `acrodistdll.dll` against the tested ISO's own payload and sets a `version=native,builtin` override for `Acrobat.exe`. These are installer-specific files, separate from the Microsoft compatibility DLLs below. Other media need a review of those checks rather than copying someone else's installation state.

The exporter currently requires this installed `Acrobat.exe` SHA-256:

```text
b4b6e679c69679091ca70fdfe847850943b729c1a5b21e179bc080a538454621
```

## Native DLL reference

[install-native-dlls.sh](../scripts/install-native-dlls.sh) is the executable source of truth for these downloads and hashes. It obtains each file from `https://msdl.microsoft.com/download/symbols/<dll>/<identifier>/<dll>`. `system32` destinations below are x64; `syswow64` destinations are x86.

| DLL | Architecture / destination | File version | Symbol-server identifier |
| --- | --- | --- | --- |
| `msftedit.dll` | x64 / `system32` | 5.41.21.2510 | `4CE7C7EDc6000` |
| `mspatcha.dll` | x64 / `system32` | 5.0.1.1 | `C2769F0911000` |
| `mspatcha.dll` | x86 / `syswow64` | 5.0.1.1 | `2DEF6682d000` |
| `riched20.dll` | x64 / `system32` | 5.31.23.1231 | `7AA93C519a000` |
| `riched20.dll` | x86 / `syswow64` | 5.31.23.1231 | `CD66E72F7a000` |
| `msls31.dll` | x64 / `system32` | 3.10.349.0 | `759635BD39000` |
| `msls31.dll` | x86 / `syswow64` | 3.10.349.0 | `A4DAE42631000` |

SHA-256, relative to `prefix/drive_c/windows/`:

```text
e15ed4fefc3010c213694331ddfdc03767682325c898d773ab243e2dc8b08461  system32/msftedit.dll
05d039a13e8aaa97592def0a385b41efc2cd7d960f501ebd5a8419a41eb9805d  system32/mspatcha.dll
362414f8120f0162cd8e88e968b25ebad422f99e5225c25df46b4c8554263541  syswow64/mspatcha.dll
4aa8d583491061ab27019ac1958378462bf952affb747fe90ecefd8ebec21d2f  system32/riched20.dll
aee7ebf38be4c4ecaa858c8e201c27628e3b5bae80b820f5dc984173fdf2cdab  syswow64/riched20.dll
0898f29460e4b725c64465dd5d781c9de893ad817eeeca6d601b19d103715e12  system32/msls31.dll
3ed04e60ec1859086a633c98448306deb95fe5dfb8da511c91e3d2c1b1f38dfb  syswow64/msls31.dll
```

The helper sets `native,builtin` overrides for `*mspatcha`, `*riched20`, and `*msls31`. `msftedit` is overridden only for `Acrobat.exe`. These values belong under Wine's `DllOverrides` keys; the scripts apply them rather than importing a private registry dump.

## Components built from source

| Component | How it is recreated |
| --- | --- |
| x64 `user32.dll` | [prepare-user32.py](../scripts/wine-compat/prepare-user32.py) takes the pinned Wine 11.18 file and forwards only `EndTask` to the shim. The original SHA-256 is pinned in that script. The result goes in `prefix/drive_c/windows/system32/`; [wine-compat.reg](../config/wine-compat.reg) scopes its native override to Acrobat. |
| x64 `wine_endtask.dll` | Compiled from [endtask.c](../scripts/wine-compat/endtask.c) and [endtask.def](../scripts/wine-compat/endtask.def) by [install-wine-compat.sh](../scripts/install-wine-compat.sh), then copied beside `user32.dll`. |
| `crypt32.dll` | Built from the pinned Wine source with [crypt32-force-close.patch](../scripts/wine-compat/crypt32-force-close.patch). It stays in the matching Wine runtime's library directory as a builtin. |
| `comdlg32.dll` | The packaged runtime applies [native-file-dialog.patch](../scripts/wine-compat/native-file-dialog.patch) and its header; the Python portal broker is provided by the package. |
| `winex11.so` | The packaged runtime applies [acrobat-popup.patch](../scripts/wine-compat/acrobat-popup.patch) for the scoped in-app popup behavior. |

[wine-runtime.nix](../packaging/wine-runtime.nix) assembles the packaged Wine runtime. [install-wine-compat.sh](../scripts/install-wine-compat.sh) assembles the earlier installation runtime with the `crypt32` correction. Avoid mixing runtime libraries from unrelated Wine builds.

The original seed's EndTask shim was built with MinGW GCC 15.2.0; the current locked setup tool bundle supplies 15.3.0. Compiler-generated DLL bytes can differ. The source and exports define the compatibility fix; preserve the private prepared seed if the exact original installed bytes are required.

## Fonts and registry settings

- Winetricks provides `corefonts` and `tahoma` using its pinned recipes.
- [prepare-ui-fonts.sh](../scripts/prepare-ui-fonts.sh) obtains Microsoft Selawik 1.01 and verifies the archive and all five font files (`selawk.ttf`, `selawkb.ttf`, `selawkl.ttf`, `selawksb.ttf`, `selawksl.ttf`).
- [install-ui-fonts.py](../scripts/install-ui-fonts.py) registers `AdobeClean*.otf` and `MyriadPro-*.otf` from the local Acrobat installation, alongside Selawik. It does not source Adobe fonts from GitHub.
- [acrobat-wine.reg](../config/acrobat-wine.reg) sets the Wine-compatible protected-mode preferences, classic UI, enabled GPU setting (`bDisableGPU=0`), font substitutions, and font smoothing.
- [configure-font-rendering.py](../scripts/configure-font-rendering.py) applies the profile's 9-point UI font and ClearType settings through the Windows APIs.
- [no-updates.reg](../config/no-updates.reg) and [configure-no-updates.py](../scripts/configure-no-updates.py) disable automatic updater policies and helpers. `finish-install.sh` also disables the registered updater service/task and removes its autostart entries.

Keep the application binaries, native DLL downloads, fonts, ISO, prepared seed/manifest, and live registry data in private storage. The public source is sufficient to record the recipe and obtain/build its components; completing a fresh install still depends on those external inputs and the interactive installer.
