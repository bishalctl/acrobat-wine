#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$(realpath -- "$0")")/scripts/env.sh"

# Keep the lock out of Wine's inherited descriptors and background services.
if [[ "${1:-}" == --locked ]]; then
    shift
else
    exec flock --nonblock --close "$ACROBAT_ROOT/state/setup.lock" \
        "$BASH" "$ACROBAT_ROOT/setup.sh" --locked "$@"
fi

mode=install
case "${1:-}" in
    --prepare-only) mode=prepare; shift ;;
    --finish) exec "$ACROBAT_ROOT/scripts/finish-install.sh" ;;
esac

# Optional local test placement; normal launches follow the desktop's rules.
if [[ "${ACROBAT_TEST_WORKSPACE:-}" == 4 && -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
    result="$(hyprctl eval "$(cat "$ACROBAT_ROOT/config/hyprland-workspace.lua")" 2>&1)"
    [[ "$result" == ok ]] || { printf '%s\n' "$result" >&2; exit 1; }
fi

for tool in wine wineboot winecfg wineserver winetricks 7z cabextract; do
    [[ -x "$ACROBAT_ROOT/.local/bin/$tool" ]] || {
        printf 'Missing tool: .local/bin/%s\n' "$tool" >&2; exit 1;
    }
done

iso="${1:-$ACROBAT_ROOT/.local/Acrobat.2026.x64/Adobe.Acrobat.2026.u17.x64.Multilingual.iso}"
iso="$(realpath -- "$iso")"
printf '%s  %s\n' a839dfadeb73ed050721f40efd2d338cda3b4f76 "$iso" | sha1sum --check --status
media="$ACROBAT_ROOT/.local/installer"
if [[ ! -f "$media/autoplay.exe" ]]; then
    mkdir -p "$media"
    "$ACROBAT_ROOT/.local/bin/7z" x -y "-o$media" "$iso" \
        > "$ACROBAT_ROOT/logs/extract-iso.log"
fi

# Prevent Adobe's online updater from running during or after installation.
export WINEDLLOVERRIDES="$WINEDLLOVERRIDES;adobearm.exe,adobearmhelper.exe,armsvc.exe=d"
if [[ ! -f "$WINEPREFIX/system.reg" ]]; then
    printf 'Creating a fresh Wine profile.\n'
    WINEDLLOVERRIDES="$WINEDLLOVERRIDES;mscoree,mshtml=" \
        "$ACROBAT_ROOT/.local/bin/wineboot" -i </dev/null \
        > "$ACROBAT_ROOT/logs/wine-initialize.log" 2>&1
    "$ACROBAT_ROOT/.local/bin/winecfg" -v win10 </dev/null \
        > "$ACROBAT_ROOT/logs/wine-configure.log" 2>&1
    # Keep Windows user folders in this profile instead of linking to Linux data.
    python3 - <<'PY'
import os
from pathlib import Path
for user in (Path(os.environ['WINEPREFIX']) / 'drive_c/users').iterdir():
    if user.is_dir():
        for name in ['Desktop', 'Documents', 'Downloads', 'Music', 'Pictures', 'Videos']:
            folder = user / name
            if folder.is_symlink():
                folder.unlink()
                folder.mkdir()
PY
fi

if [[ ! -f "$ACROBAT_ROOT/state/prerequisites-installed" ]]; then
    printf 'Installing Windows fonts. The ISO supplies its own runtimes.\n'
    wine_binary="$(readlink -f -- "$WINE")"
    WINE="$wine_binary" WINELOADER="$wine_binary" WINETRICKS_GUI=none \
        "$ACROBAT_ROOT/.local/bin/winetricks" -q corefonts tahoma \
        </dev/null > "$ACROBAT_ROOT/logs/winetricks-prerequisites.log" 2>&1
    "$ACROBAT_ROOT/scripts/install-native-dlls.sh" </dev/null \
        > "$ACROBAT_ROOT/logs/native-dlls-install.log" 2>&1
    "$ACROBAT_ROOT/scripts/install-wine-compat.sh" </dev/null \
        > "$ACROBAT_ROOT/logs/install-wine-compat.log" 2>&1
    touch "$ACROBAT_ROOT/state/prerequisites-installed"
fi

for settings in acrobat-wine no-updates; do
    path="$("$ACROBAT_ROOT/.local/bin/winepath" -w "$ACROBAT_ROOT/config/$settings.reg")"
    "$WINE" reg import "${path%$'\r'}" </dev/null \
        > "$ACROBAT_ROOT/logs/$settings-settings.log" 2>&1
done
"$WINE" reg add 'HKLM\Software\Policies\Microsoft\Windows\Installer' \
    /v Logging /t REG_SZ /d voicewarmupx /f </dev/null \
    > "$ACROBAT_ROOT/logs/installer-logging.log" 2>&1

[[ "$mode" != prepare ]] || { printf 'Fresh profile and ISO launcher are ready.\n'; exit 0; }

if [[ -f "$WINEPREFIX/drive_c/Program Files/Adobe/Acrobat DC/Acrobat/Acrobat.exe" ]]; then
    printf 'Acrobat is already installed. No update will be performed.\n'
    exec "$ACROBAT_ROOT/scripts/finish-install.sh"
fi

# Wine otherwise selects Languages.cab for many of the MSP's binary deltas.
# Keep the ISO workflow, using a copy with only that media boundary corrected.
patch_script="$("$ACROBAT_ROOT/.local/bin/winepath" -w "$ACROBAT_ROOT/scripts/prepare-update.py")"
"$WINE" "$ACROBAT_ROOT/.local/python-windows/python.exe" "${patch_script%$'\r'}" \
    --prepare-update </dev/null > "$ACROBAT_ROOT/logs/prepare-iso-patch.log" 2>&1
python3 - "$iso" <<'PY'
import os, subprocess, sys
from pathlib import Path
root = Path(os.environ['ACROBAT_ROOT'])
original = subprocess.check_output([
    str(root / '.local/bin/7z'), 'x', '-so', sys.argv[1], 'Adobe Acrobat/setup.ini',
])
old = b'PATCH=AcrobatDCx64Upd2600221931.msp'
new = br'PATCH=..\wine-compatible\AcrobatDCx64Upd2600221931-wine.msp'
assert original.count(old) == 1
prepared = original.replace(old, new)
target = root / '.local/installer/Adobe Acrobat/setup.ini'
if target.read_bytes() not in [original, prepared]:
    raise SystemExit('The extracted setup.ini has additional edits; refusing to overwrite them.')
(root / '.local/installer/wine-compatible/setup-original.ini').write_bytes(original)
target.write_bytes(prepared)
PY

python3 "$ACROBAT_ROOT/scripts/prepare-iso-runtime.py" \
    </dev/null > "$ACROBAT_ROOT/logs/iso-runtime-preparation.log" 2>&1

printf 'Opening the supplied autoplay.exe.\n'
cd -- "$media"
printf '\n[%s] Starting original ISO workflow\n' "$(date --iso-8601=seconds)" \
    >> "$ACROBAT_ROOT/logs/autoplay.log"
"$WINE" ./autoplay.exe </dev/null >> "$ACROBAT_ROOT/logs/autoplay.log" 2>&1
printf 'When the bundled installer finishes, run ./setup.sh --finish.\n'
