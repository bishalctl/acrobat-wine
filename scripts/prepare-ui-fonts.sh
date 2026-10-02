#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$(realpath -- "$0")")/env.sh"

# Microsoft's open Segoe UI replacement, fixed at release 1.01.
archive="$ACROBAT_ROOT/.local/downloads/selawik/Selawik_Release.zip"
digest=3f62c51e05e3b5a1e6241cf92a371f0be2ea1183aa87b30718bbd40832a8d423
mkdir -p "$(dirname -- "$archive")"
if [[ ! -f "$archive" ]]; then
    curl --fail --location --retry 2 --output "$archive.partial" \
        'https://github.com/microsoft/Selawik/releases/download/1.01/Selawik_Release.zip'
    printf '%s  %s\n' "$digest" "$archive.partial" | sha256sum --check --status
    mv -- "$archive.partial" "$archive"
fi
printf '%s  %s\n' "$digest" "$archive" | sha256sum --check --status

python3 - "$archive" <<'PY'
import hashlib, os, sys, zipfile
from pathlib import Path
destination = Path(os.environ['ACROBAT_ROOT']) / '.local/fonts/selawik'
destination.mkdir(parents=True, exist_ok=True)
expected = {
    'selawk.ttf': 'e9d98518d8ac2817782a9a382430463a2e0793ea68350b695bb727d9a830ee1c',
    'selawkb.ttf': 'f0db5e174a90e0956ad7d2844bdca1d5e6da92ec65b2c04e57ba9b180668c904',
    'selawkl.ttf': '8e19d073091a1e869b5b0d48b925e605c0a4c6ece7df7b22a364fb065314c4c5',
    'selawksb.ttf': '0a9e9d0549a10f24bef9b3a29e06fe6e0b5c21e7a784c503b048a307841a7783',
    'selawksl.ttf': '8620960344f12093482cded984a1aafa5a57d24cbf7e9299da125ccf0e9d4102',
}
with zipfile.ZipFile(sys.argv[1]) as archive:
    for name, digest in expected.items():
        data = archive.read(name)
        assert hashlib.sha256(data).hexdigest() == digest, name
        target = destination / name
        if not target.exists():
            target.write_bytes(data)
        else:
            assert target.read_bytes() == data, target
print('Verified Microsoft Selawik 1.01: light, semilight, regular, semibold, bold.')
PY

license="$ACROBAT_ROOT/.local/fonts/selawik/LICENSE.txt"
if [[ ! -f "$license" ]]; then
    curl --fail --location --retry 2 --output "$(dirname -- "$archive")/license.json" \
        'https://api.github.com/repos/microsoft/Selawik/contents/LICENSE.txt?ref=1.01'
    python3 - "$(dirname -- "$archive")/license.json" "$license" <<'PY'
import base64, hashlib, json, sys
from pathlib import Path
data = base64.b64decode(json.loads(Path(sys.argv[1]).read_text())['content'])
assert hashlib.sha256(data).hexdigest() == '77b7c2506d4efb22e09c8ccf10159f4956eab3ef7c007fef95de136bcf45300c'
Path(sys.argv[2]).write_bytes(data)
PY
fi
printf '%s  %s\n' 77b7c2506d4efb22e09c8ccf10159f4956eab3ef7c007fef95de136bcf45300c "$license" \
    | sha256sum --check --status
