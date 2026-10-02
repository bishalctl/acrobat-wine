"""Let the ISO replace Wine's synthetic runtime files before applying its MSP.

Wine's MSI compares the high version of a builtin DLL with the packaged file,
keeps the builtin, then tries to apply an Adobe delta to those unrelated bytes.
Only builtin msvcp140.dll files explicitly supplied in this ISO's system
directories are removed. Wine's core runtime, native libraries, Adobe
payloads, and the ISO are left intact.
"""
import ctypes as C
import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent

if os.name != 'nt':
    if os.environ.get('WINEPREFIX') != str(ROOT / 'prefix'):
        raise SystemExit('Use setup.sh to prepare this project\'s Wine profile.')
    # Query through Wine, then unlink from Linux. Windows refuses to delete
    # runtime DLLs while the query process or a Wine service has them mapped.
    script = 'Z:' + str(Path(__file__).resolve()).replace('/', '\\')
    scan = subprocess.check_output([
        str(ROOT / '.local/bin/wine'),
        str(ROOT / '.local/python-windows/python.exe'), script,
    ], stdin=subprocess.DEVNULL, text=True)
    candidates = json.loads(scan)['wine_builtins']
    removed = []
    handled = set()
    for candidate in candidates:
        parts = PureWindowsPath(candidate['path']).parts
        assert len(parts) == 4 and parts[0].upper() == 'C:\\'
        assert parts[1].lower() == 'windows'
        assert parts[2].lower() in ['system32', 'syswow64']
        folder = ROOT / 'prefix/drive_c/windows' / parts[2].lower()
        matches = [p for p in folder.iterdir() if p.name.lower() == parts[3].lower()]
        if not matches:
            continue
        assert len(matches) == 1
        target = matches[0]
        if target in handled:
            continue
        handled.add(target)
        assert target.is_file() and not target.is_symlink()
        with target.open('rb') as source:
            assert source.read(80)[0x40:0x50] == b'Wine builtin DLL', target
        target.unlink()
        removed.append({**candidate, 'linux_path': str(target)})
    report = {'removed_wine_builtins': removed}
    (ROOT / 'state/iso-runtime-preparation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    sys.exit(0)

from ctypes import wintypes as W
m = C.WinDLL('msi')
def fn(name, args, result=W.UINT):
    f = getattr(m, name)
    f.argtypes, f.restype = args, result
    return f
open_db = fn('MsiOpenDatabaseW', [W.LPCWSTR, C.c_void_p, C.POINTER(W.UINT)])
open_view = fn('MsiDatabaseOpenViewW', [W.UINT, W.LPCWSTR, C.POINTER(W.UINT)])
execute = fn('MsiViewExecute', [W.UINT, W.UINT])
fetch = fn('MsiViewFetch', [W.UINT, C.POINTER(W.UINT)])
get = fn('MsiRecordGetStringW', [W.UINT, W.UINT, W.LPWSTR, C.POINTER(W.DWORD)])
count = fn('MsiRecordGetFieldCount', [W.UINT])
close = fn('MsiCloseHandle', [W.UINT])
h = W.UINT()
assert open_db(str(ROOT / '.local/installer/Adobe Acrobat/AcroPro.msi'), None, C.byref(h)) == 0

def query(sql):
    view = W.UINT()
    assert open_view(h, sql, C.byref(view)) == 0
    assert execute(view, 0) == 0
    rows = []
    while True:
        rec = W.UINT()
        result = fetch(view, C.byref(rec))
        if result == 259:
            break
        assert result == 0
        row = []
        for index in range(1, count(rec) + 1):
            text, size = C.create_unicode_buffer(2048), W.DWORD(2048)
            assert get(rec, index, text, C.byref(size)) == 0
            row.append(text.value)
        close(rec)
        rows.append(row)
    close(view)
    return rows

components = {row[0]: row[1] for row in query('SELECT `Component`, `Directory_` FROM `Component`')}
directories = {row[0]: row[1:] for row in query('SELECT `Directory`, `Directory_Parent`, `DefaultDir` FROM `Directory`')}
files = query('SELECT `File`, `Component_`, `FileName` FROM `File`')
close(h)
roots = {'SystemFolder': Path('C:/windows/syswow64'), 'System64Folder': Path('C:/windows/system32')}

def directory(name, seen=None):
    # Merge modules append their GUID to standard directory identifiers.
    # Adobe's VC runtime files use SystemFolder.<GUID>/System64Folder.<GUID>.
    standard_name = name.split('.', 1)[0]
    if standard_name in roots:
        return roots[standard_name]
    seen = set() if seen is None else seen
    if name in seen or name not in directories:
        return None
    seen.add(name)
    parent, leaf = directories[name]
    base = directory(parent, seen)
    if base is None:
        return None
    leaf = leaf.split(':', 1)[0].split('|')[-1]
    return base if leaf in ['', '.'] else base / leaf

candidates = []
for file_id, component, filename in files:
    folder = directory(components[component])
    filename = filename.split('|')[-1]
    if folder is None or filename.lower() != 'msvcp140.dll':
        continue
    target = folder / filename
    if target.is_file():
        with target.open('rb') as source:
            header = source.read(80)
        if header[0x40:0x50] == b'Wine builtin DLL':
            candidates.append({'file_id': file_id, 'path': str(target)})
print(json.dumps({'wine_builtins': candidates}, indent=2))
