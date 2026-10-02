"""Register Adobe and Microsoft Selawik UI fonts in this Wine profile."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import shutil
import struct
import winreg as R

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path('C:/Program Files/Adobe/Acrobat DC/Acrobat/WebResources/Resource1/app1/fonts')
DESTINATION = Path('C:/windows/Fonts')
gdi = C.WinDLL('gdi32', use_last_error=True)
gdi.AddFontResourceExW.argtypes = [W.LPCWSTR, W.DWORD, C.c_void_p]
gdi.AddFontResourceExW.restype = C.c_int

def full_name(path):
    data = path.read_bytes()
    table_count = struct.unpack_from('>H', data, 4)[0]
    for index in range(table_count):
        tag, _, offset, _ = struct.unpack_from('>4sIII', data, 12 + 16 * index)
        if tag == b'name':
            break
    else:
        raise ValueError('Font has no name table: ' + str(path))
    _, count, storage = struct.unpack_from('>HHH', data, offset)
    for index in range(count):
        platform, _, language, name_id, length, start = struct.unpack_from('>6H', data, offset + 6 + 12 * index)
        if platform == 3 and language == 0x409 and name_id == 4:
            return data[offset + storage + start:offset + storage + start + length].decode('utf-16-be')
    raise ValueError('Font has no English Windows full name: ' + str(path))

report = []
fonts = sorted([*SOURCE.glob('AdobeClean*.otf'), *SOURCE.glob('MyriadPro-*.otf'),
                *(SOURCE.parents[3] / 'CrashReporterResources').glob('AdobeClean-*.otf')])
assert fonts, 'The installed Acrobat UI fonts were not found'
extra = sorted((ROOT / '.local/fonts/selawik').glob('*.ttf'))
assert len(extra) == 5, 'Run scripts/prepare-ui-fonts.sh to obtain the five Selawik weights'
fonts += extra
for source in fonts:
    name = full_name(source)
    target = DESTINATION / source.name
    if not target.exists():
        shutil.copyfile(source, target)
    else:
        assert target.read_bytes() == source.read_bytes(), target
    for view in [R.KEY_WOW64_64KEY, R.KEY_WOW64_32KEY]:
        with R.CreateKeyEx(R.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts', 0, R.KEY_SET_VALUE | view) as key:
            kind = 'TrueType' if target.suffix.lower() == '.ttf' else 'OpenType'
            R.SetValueEx(key, name + ' (' + kind + ')', 0, R.REG_SZ, target.name)
    added = gdi.AddFontResourceExW(str(target), 0, None)
    report.append({'file': target.name, 'name': name, 'font_resources_added': added})

user = C.WinDLL('user32')
user.SendNotifyMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
user.SendNotifyMessageW.restype = W.BOOL
user.SendNotifyMessageW(0xffff, 0x1d, 0, 0)  # WM_FONTCHANGE, without activation.
(ROOT / 'state/ui-fonts.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, indent=2))
