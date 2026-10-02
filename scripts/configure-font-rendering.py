"""Apply profile-local smoothing and consistent 9-point Windows UI fonts."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

class LOGFONT(C.Structure):
    _fields_ = [(name, W.LONG) for name in ['height', 'width', 'escapement', 'orientation', 'weight']] + [
        (name, W.BYTE) for name in ['italic', 'underline', 'strikeout', 'charset', 'outprecision', 'clipprecision', 'quality', 'pitch']
    ] + [('face', W.WCHAR * 32)]

class METRICS(C.Structure):
    _fields_ = [('size', W.UINT)] + [(n, C.c_int) for n in ['border', 'scroll_width', 'scroll_height', 'caption_width', 'caption_height']] + [
        ('caption', LOGFONT), ('small_caption_width', C.c_int), ('small_caption_height', C.c_int),
        ('small_caption', LOGFONT), ('menu_width', C.c_int), ('menu_height', C.c_int),
        ('menu', LOGFONT), ('status', LOGFONT), ('message', LOGFONT), ('padded_border', C.c_int)]

user, gdi = C.WinDLL('user32', use_last_error=True), C.WinDLL('gdi32')
user.SystemParametersInfoW.argtypes = [W.UINT, W.UINT, C.c_void_p, W.UINT]
user.SystemParametersInfoW.restype = W.BOOL
user.GetDC.argtypes = [W.HWND]; user.GetDC.restype = W.HDC
user.ReleaseDC.argtypes = [W.HWND, W.HDC]
gdi.GetDeviceCaps.argtypes = [W.HDC, C.c_int]

def spi(action, value=0, pointer=None, persist=False):
    assert user.SystemParametersInfoW(action, value, pointer, 3 if persist else 0), (action, C.get_last_error())

metrics = METRICS(); metrics.size = C.sizeof(metrics)
spi(0x29, metrics.size, C.byref(metrics))  # SPI_GETNONCLIENTMETRICS
checkpoint = ROOT / 'state/checkpoints/font-styles-before/nonclientmetrics.bin'
checkpoint.parent.mkdir(parents=True, exist_ok=True)
if not checkpoint.exists():
    checkpoint.write_bytes(bytes(metrics))

dc = user.GetDC(None)
try:
    dpi = gdi.GetDeviceCaps(dc, 90)
finally:
    user.ReleaseDC(None, dc)

for name in ['caption', 'small_caption', 'menu', 'status', 'message']:
    font = getattr(metrics, name)
    font.face = 'Segoe UI'
    font.height = -round(9 * dpi / 72)
    font.weight = 400
    font.quality = 5  # CLEARTYPE_QUALITY
spi(0x2a, metrics.size, C.byref(metrics), True)  # SPI_SETNONCLIENTMETRICS
spi(0x4b, 1, persist=True)  # SPI_SETFONTSMOOTHING
spi(0x200b, pointer=C.c_void_p(2), persist=True)  # ClearType
spi(0x200d, pointer=C.c_void_p(1400), persist=True)  # Contrast
spi(0x2013, pointer=C.c_void_p(1), persist=True)  # RGB

spi(0x29, metrics.size, C.byref(metrics))
report = {'dpi': dpi, 'point_size': 9, 'system_fonts': {}, 'smoothing': {}}
for name in ['caption', 'small_caption', 'menu', 'status', 'message']:
    font = getattr(metrics, name)
    # Wine may return the resolved family rather than the replacement's alias.
    assert font.face in ['Segoe UI', 'Selawik'] and font.weight == 400 and font.quality == 5
    report['system_fonts'][name] = dict(face=font.face, height=font.height, weight=font.weight, quality=font.quality)
for name, action, expected in [('enabled', 0x4a, 1), ('type', 0x200a, 2), ('contrast', 0x200c, 1400), ('orientation', 0x2012, 1)]:
    value = W.UINT()
    spi(action, pointer=C.byref(value))
    assert value.value == expected, (name, value.value)
    report['smoothing'][name] = value.value
(ROOT / 'state/font-rendering-settings.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, indent=2))
