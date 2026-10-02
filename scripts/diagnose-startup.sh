#!/usr/bin/env bash
# Capture one startup in the environment that actually launches Acrobat.
# No GPU, renderer, driver, or registry settings are changed by this script.
set -euo pipefail
source "$(dirname -- "$(realpath -- "$0")")/env.sh"

report="$(mktemp -d "$ACROBAT_ROOT/logs/startup-$(date +%Y%m%d-%H%M%S)-XXXXXX")"
export ACROBAT_LOG="$report/wine.log"
export WINEDEBUG='-all,err+all,+timestamp,+debugstr,+seh'

{
    date --iso-8601=seconds
    printf 'Wine: '
    "$WINE" --version
    printf 'Acrobat: '
    python3 "$ACROBAT_ROOT/scripts/version.py"
    printf 'WINEPREFIX=%s\n' "$WINEPREFIX"
    for name in DISPLAY WAYLAND_DISPLAY LD_LIBRARY_PATH LIBGL_DRIVERS_PATH \
        __EGL_VENDOR_LIBRARY_FILENAMES __GLX_VENDOR_LIBRARY_NAME \
        VK_ICD_FILENAMES LIBGL_ALWAYS_SOFTWARE; do
        printf '%s=%s\n' "$name" "${!name-<unset>}"
    done
    for device in /dev/dri/renderD* /dev/nvidia[0-9]* /dev/nvidiactl; do
        [[ -e "$device" ]] && ls -l -- "$device"
    done
    if command -v nvidia-smi >/dev/null; then
        timeout 10 nvidia-smi --query-gpu=name,driver_version,utilization.gpu \
            --format=csv || true
    fi
    if command -v glxinfo >/dev/null; then
        timeout 10 glxinfo -B || true
    fi
} > "$report/graphics.txt" 2>&1

printf 'Startup diagnostics: %s\n' "$report"
"$ACROBAT_ROOT/acrobat" "$@" &
launch_pid=$!

# Observe only this profile's processes; do not activate windows or send input.
(
    for sample in 1 2 3; do
        sleep 5
        kill -0 "$launch_pid" 2>/dev/null || break
        python3 - "$WINEPREFIX" <<'PY' > "$report/processes-$sample.json"
import json, pathlib, sys
prefix = ('WINEPREFIX=' + sys.argv[1]).encode()
rows = []
for proc in pathlib.Path('/proc').glob('[0-9]*'):
    try:
        if prefix not in (proc / 'environ').read_bytes().split(b'\0'):
            continue
        args = (proc / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
        if not args or not any(s in args[0].lower() for s in
                               [b'acrobat.exe', b'acrocef.exe', b'winedbg']):
            continue
        rows.append({'pid': int(proc.name),
                     'command': [a.decode(errors='replace') for a in args]})
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
print(json.dumps(rows, indent=2))
PY
    done
) &
observer_pid=$!

set +e
wait "$launch_pid"
launch_status=$?
kill "$observer_pid" 2>/dev/null
wait "$observer_pid" 2>/dev/null
printf '%s\n' "$launch_status" > "$report/exit-status.txt"
printf 'Acrobat exited with status %s. Diagnostics: %s\n' "$launch_status" "$report"
exit "$launch_status"
