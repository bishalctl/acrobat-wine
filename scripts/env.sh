#!/usr/bin/env bash
# Shared environment for this project's dedicated Wine profile.
ACROBAT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export ACROBAT_ROOT
export PATH="$ACROBAT_ROOT/.local/bin:$PATH"
export WINE="$ACROBAT_ROOT/.local/bin/wine"
export WINESERVER="$ACROBAT_ROOT/.local/bin/wineserver"
export WINEPREFIX="$ACROBAT_ROOT/prefix"
export WINEARCH=win64
export XDG_CACHE_HOME="$ACROBAT_ROOT/state/cache"
export XDG_CONFIG_HOME="$ACROBAT_ROOT/state/config"
export XDG_DATA_HOME="$ACROBAT_ROOT/state/share"
export W_CACHE="$ACROBAT_ROOT/.local/downloads/winetricks"
export WINEDEBUG="${WINEDEBUG:--all,err+all,warn+seh,+timestamp,+debugstr}"
export WINEDLLOVERRIDES="winemenubuilder.exe=d${WINEDLLOVERRIDES:+;$WINEDLLOVERRIDES}"
mkdir -p "$ACROBAT_ROOT/logs" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME"
