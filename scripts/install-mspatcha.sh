#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$(realpath -- "$0")")/env.sh"

# Microsoft symbol-server binaries, indexed by https://winbindex.m417z.com/?file=mspatcha.dll
install_patch_dll() {
    local architecture="$1" directory="$2" identifier="$3" digest="$4"
    local source="$ACROBAT_ROOT/.local/dlls/mspatcha/$architecture/mspatcha.dll"
    mkdir -p "$(dirname -- "$source")"
    if [[ ! -f "$source" ]]; then
        curl --fail --location --retry 2 \
            --output "$source.partial" \
            "https://msdl.microsoft.com/download/symbols/mspatcha.dll/$identifier/mspatcha.dll"
        printf '%s  %s\n' "$digest" "$source.partial" | sha256sum --check --status
        mv -- "$source.partial" "$source"
    fi
    printf '%s  %s\n' "$digest" "$source" | sha256sum --check --status
    cp --remove-destination -- "$source" "$WINEPREFIX/drive_c/windows/$directory/mspatcha.dll"
}

install_patch_dll x64 system32 C2769F0911000 \
    05d039a13e8aaa97592def0a385b41efc2cd7d960f501ebd5a8419a41eb9805d
install_patch_dll x86 syswow64 2DEF6682d000 \
    362414f8120f0162cd8e88e968b25ebad422f99e5225c25df46b4c8554263541

"$WINE" reg add 'HKCU\Software\Wine\DllOverrides' \
    /v '*mspatcha' /t REG_SZ /d native,builtin /f
