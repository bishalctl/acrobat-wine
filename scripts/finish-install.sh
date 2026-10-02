#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$(realpath -- "$0")")/env.sh"

acrobat_dir="$WINEPREFIX/drive_c/Program Files/Adobe/Acrobat DC/Acrobat"
[[ -f "$acrobat_dir/Acrobat.exe" ]] || { printf 'The supplied installer has not finished.\n' >&2; exit 1; }
version="$(python3 "$ACROBAT_ROOT/scripts/version.py")"
[[ "$version" == 26.002.21931 ]] || {
    printf 'The supplied installation is incomplete: found version %s.\n' "$version" >&2; exit 1;
}

# The ISO's wrapper must finish before applying the final Wine settings.
python3 - <<'PY'
import hashlib, os, subprocess
from pathlib import Path
root = Path(os.environ['ACROBAT_ROOT'])
archive = root / '.local/installer/Adobe Acrobat/crack.exe'
installed = Path(os.environ['WINEPREFIX']) / 'drive_c/Program Files/Adobe/Acrobat DC/Acrobat'
for name in ['version.dll', 'acrodistdll.dll']:
    source = subprocess.check_output([str(root / '.local/bin/7z'), 'x', '-so', str(archive), name])
    target = installed / name
    if not target.is_file() or hashlib.sha256(source).digest() != hashlib.sha256(target.read_bytes()).digest():
        raise SystemExit('The bundled wrapper has not completed: ' + name + ' does not match its payload.')
print('The installed payload matches the supplied ISO wrapper.')
PY

# Also repair existing profiles whose original prerequisite marker predates
# the native RICHEDIT50W control. Matching installed bytes are left in place.
"$ACROBAT_ROOT/scripts/install-native-dlls.sh" --msftedit-only
"$BASH" "$ACROBAT_ROOT/scripts/prepare-ui-fonts.sh"

for settings in acrobat-wine no-updates; do
    path="$("$ACROBAT_ROOT/.local/bin/winepath" -w "$ACROBAT_ROOT/config/$settings.reg")"
    "$WINE" reg import "${path%$'\r'}" </dev/null
done

# Register the UI font files included with Acrobat in this profile only.
path="$("$ACROBAT_ROOT/.local/bin/winepath" -w "$ACROBAT_ROOT/scripts/install-ui-fonts.py")"
"$WINE" "$ACROBAT_ROOT/.local/python-windows/python.exe" "${path%$'\r'}" </dev/null

path="$("$ACROBAT_ROOT/.local/bin/winepath" -w "$ACROBAT_ROOT/scripts/configure-font-rendering.py")"
"$WINE" "$ACROBAT_ROOT/.local/python-windows/python.exe" "${path%$'\r'}" </dev/null

# Prefer the application-local DLL supplied by this ISO for Acrobat alone.
"$WINE" reg add 'HKCU\Software\Wine\AppDefaults\Acrobat.exe\DllOverrides' \
    /v version /t REG_SZ /d native,builtin /f </dev/null

# Disable the updater even if Setup registered it after the initial policies.
"$WINE" sc stop AdobeARMservice </dev/null || true
"$WINE" sc config AdobeARMservice start= disabled </dev/null || true
"$WINE" schtasks /delete /f /tn 'Adobe Acrobat Update Task' </dev/null || true
for key in 'HKLM\Software\Microsoft\Windows\CurrentVersion\Run' \
           'HKLM\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Run'; do
    "$WINE" reg delete "$key" /v 'Adobe ARM' /f </dev/null || true
    "$WINE" reg delete "$key" /v 'Acrobat Assistant 8.0' /f </dev/null || true
done

path="$("$ACROBAT_ROOT/.local/bin/winepath" -w "$ACROBAT_ROOT/scripts/configure-no-updates.py")"
"$WINE" "$ACROBAT_ROOT/.local/python-windows/python.exe" "${path%$'\r'}" </dev/null

printf '%s\n' "$version" > "$ACROBAT_ROOT/state/install-complete"
printf 'Installed version: %s. Updater policy and service settings applied.\n' "$version"
