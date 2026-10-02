#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$(realpath -- "$0")")/env.sh"

export XDG_CACHE_HOME="$ACROBAT_ROOT/state/cache"
export XDG_CONFIG_HOME="$ACROBAT_ROOT/state/config"
mkdir -p "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME"
base="$(nix build --file "$ACROBAT_ROOT/scripts/wine-compat/crypt32.nix" \
    --arg baseOnly true --no-link --print-out-paths \
    --option substituters https://cache.nixos.org)"
compat="$ACROBAT_ROOT/.local/wine-compat"
runtime="$ACROBAT_ROOT/.local/wine-runtime"
component="$compat/crypt32-build"
compiler="$ACROBAT_ROOT/.local/bin/x86_64-w64-mingw32-gcc"
mkdir -p "$compat"

printf '%s  %s\n' \
    9304ff56ab3b1ca5d08dca51e89c1737359dcf09c2dce17e84396f9c2518919e \
    "$base/lib/wine/x86_64-windows/user32.dll" | sha256sum --check --status

if [[ ! -f "$component/lib/wine/x86_64-windows/crypt32.dll" ]]; then
    nix build --file "$ACROBAT_ROOT/scripts/wine-compat/crypt32.nix" \
        --out-link "$component" --cores 2 --max-jobs 1 \
        --option substituters https://cache.nixos.org \
        > "$ACROBAT_ROOT/logs/wine-crypt32-build.log" 2>&1
fi
if [[ ! -x "$compiler" ]]; then
    printf 'Missing compiler: %s\n' "$compiler" >&2
    exit 1
fi
"$compiler" -shared -Os -fno-stack-protector -nostdlib \
    -Wl,--entry,0 -Wl,--no-insert-timestamp \
    -o "$compat/wine_endtask.dll" \
    "$ACROBAT_ROOT/scripts/wine-compat/endtask.c" \
    "$ACROBAT_ROOT/scripts/wine-compat/endtask.def" \
    -luser32 -lkernel32 -lgcc
python3 "$ACROBAT_ROOT/scripts/wine-compat/prepare-user32.py" \
    "$base/lib/wine/x86_64-windows/user32.dll" "$compat/user32.dll"

"$WINE" tasklist /fo csv </dev/null > "$ACROBAT_ROOT/state/compat-processes.csv" \
    2> "$ACROBAT_ROOT/logs/compat-process-check.log"
if rg -qi '^"(Acrobat|AcroRd32)\.exe"' "$ACROBAT_ROOT/state/compat-processes.csv"; then
    printf 'Close Acrobat before updating this profile’s Wine libraries.\n' >&2
    exit 1
fi
settings="$("$ACROBAT_ROOT/.local/bin/winepath" -w "$ACROBAT_ROOT/config/wine-compat.reg")"
"$WINE" reg import "${settings%$'\r'}" </dev/null \
    > "$ACROBAT_ROOT/logs/wine-compat-registry.log" 2>&1
"$WINESERVER" -k
"$WINESERVER" -w

if [[ ! -d "$runtime" ]]; then
    mkdir -p "$runtime"
    cp -rs --no-preserve=mode -- "$base/." "$runtime/"
fi
# Wine locates its DLL directory through the real path of ntdll.so.
# Copy these loaders so that the local crypt32 remains a Wine builtin and
# continues to use Wine's matching Unix library for certificates and DPAPI.
for file in lib/wine/x86_64-unix/wine lib/wine/x86_64-unix/wine-preloader lib/wine/x86_64-unix/ntdll.so; do
    cp --remove-destination -- "$base/$file" "$runtime/$file"
done
ln -sfn -- ../lib/wine/x86_64-unix/wine "$runtime/bin/wine"
for tool in wineboot winecfg winepath winedbg wineconsole msiexec regedit regsvr32 notepad; do
    ln -sfn -- wine "$runtime/bin/$tool"
done
cp --remove-destination -- "$component/lib/wine/x86_64-windows/crypt32.dll" \
    "$runtime/lib/wine/x86_64-windows/crypt32.dll"

backup="$ACROBAT_ROOT/state/checkpoints/wine-compat-originals-11.18"
mkdir -p "$backup"
if [[ ! -f "$backup/user32.dll" ]]; then
    cp -- "$base/lib/wine/x86_64-windows/user32.dll" "$backup/user32.dll"
fi
cp --remove-destination -- "$compat/user32.dll" "$WINEPREFIX/drive_c/windows/system32/user32.dll"
cp --remove-destination -- "$compat/wine_endtask.dll" "$WINEPREFIX/drive_c/windows/system32/wine_endtask.dll"
for tool in wine wineboot winecfg winepath winedbg wineserver; do
    ln -sfn -- "$runtime/bin/$tool" "$ACROBAT_ROOT/.local/bin/$tool"
done
printf 'Installed Wine 11.18 compatibility libraries in %s.\n' "$runtime"
