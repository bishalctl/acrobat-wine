#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$(realpath -- "$0")")/env.sh"

# Microsoft symbol-server files, with verified hashes.
# The x64 RichEdit replacement avoids Wine's startup stack overflow in Acrobat.
install_dll() {
    local name="$1" architecture="$2" identifier="$3" digest="$4"
    local directory=system32
    local source="$ACROBAT_ROOT/.local/dlls/$name/$architecture/$name.dll"
    [[ "$architecture" != x86 ]] || directory=syswow64
    mkdir -p "$(dirname -- "$source")"
    if [[ ! -f "$source" ]]; then
        curl --fail --location --retry 2 --output "$source.partial" \
            "https://msdl.microsoft.com/download/symbols/$name.dll/$identifier/$name.dll"
        printf '%s  %s\n' "$digest" "$source.partial" | sha256sum --check --status
        mv -- "$source.partial" "$source"
    fi
    printf '%s  %s\n' "$digest" "$source" | sha256sum --check --status
    local target="$WINEPREFIX/drive_c/windows/$directory/$name.dll"
    if ! printf '%s  %s\n' "$digest" "$target" | sha256sum --check --status 2>/dev/null; then
        cp --remove-destination -- "$source" "$target"
    fi
}

# Windows 7's msftedit registers RICHEDIT50W without newer, unimplemented
# Windows shim APIs. This hash also matches Winetricks' pinned SP1 package.
install_dll msftedit x64 4CE7C7EDc6000 \
    e15ed4fefc3010c213694331ddfdc03767682325c898d773ab243e2dc8b08461
"$WINE" reg add 'HKCU\Software\Wine\AppDefaults\Acrobat.exe\DllOverrides' \
    /v msftedit /t REG_SZ /d native,builtin /f </dev/null
if [[ "${1:-}" == --msftedit-only ]]; then
    exit 0
fi

install_dll mspatcha x64 C2769F0911000 \
    05d039a13e8aaa97592def0a385b41efc2cd7d960f501ebd5a8419a41eb9805d
install_dll mspatcha x86 2DEF6682d000 \
    362414f8120f0162cd8e88e968b25ebad422f99e5225c25df46b4c8554263541
install_dll riched20 x64 7AA93C519a000 \
    4aa8d583491061ab27019ac1958378462bf952affb747fe90ecefd8ebec21d2f
install_dll riched20 x86 CD66E72F7a000 \
    aee7ebf38be4c4ecaa858c8e201c27628e3b5bae80b820f5dc984173fdf2cdab
install_dll msls31 x64 759635BD39000 \
    0898f29460e4b725c64465dd5d781c9de893ad817eeeca6d601b19d103715e12
install_dll msls31 x86 A4DAE42631000 \
    3ed04e60ec1859086a633c98448306deb95fe5dfb8da511c91e3d2c1b1f38dfb

for name in mspatcha riched20 msls31; do
    "$WINE" reg add 'HKCU\Software\Wine\DllOverrides' \
        /v "*$name" /t REG_SZ /d native,builtin /f
done
