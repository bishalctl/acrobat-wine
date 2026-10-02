#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "$(realpath -- "$0")")/.." && pwd)"
cd -- "$root"
python3 packaging/export-profile.py --prefix prefix --output packaging/payload
python3 - <<'PY'
import hashlib, json, os, shutil
from pathlib import Path
source=Path('.local/Acrobat.2026.x64/Adobe.Acrobat.2026.u17.x64.Multilingual.iso')
with source.open('rb') as file:
    digest=hashlib.file_digest(file,'sha1').hexdigest()
if digest != 'a839dfadeb73ed050721f40efd2d338cda3b4f76':
    raise SystemExit('The source ISO does not match the supplied manifest.')
target=Path('packaging/payload')/source.name
if not target.exists():
    try: os.link(source,target)
    except OSError: shutil.copyfile(source,target)
with target.open('rb') as file:
    if hashlib.file_digest(file,'sha1').hexdigest()!=digest:
        raise SystemExit('The existing bundled ISO differs; it has been left intact.')
manifest=Path('packaging/payload/manifest.json')
data=json.loads(manifest.read_text())
data['iso']={'file':source.name,'sha1':digest,'bytes':source.stat().st_size}
temporary=manifest.with_name('.manifest-iso.json.partial')
temporary.write_text(json.dumps(data,indent=2)+'\n')
temporary.replace(manifest)
print('Included the original ISO; checksum verified.')
PY
