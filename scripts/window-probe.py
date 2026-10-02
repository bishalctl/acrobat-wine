import ctypes as C
from ctypes import wintypes as W
import json
import sys
import time

u = C.WinDLL('user32', use_last_error=True)
u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
u.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
u.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
u.GetWindowThreadProcessId.restype = W.DWORD
u.GetWindow.argtypes = [W.HWND, W.UINT]
u.GetWindow.restype = W.HWND
u.GetLastActivePopup.argtypes = [W.HWND]
u.GetLastActivePopup.restype = W.HWND
u.GetForegroundWindow.restype = W.HWND
u.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT, C.POINTER(C.c_size_t)]
u.SendMessageTimeoutW.restype = W.LPARAM
for name in ['IsWindowVisible', 'IsWindowEnabled', 'IsHungAppWindow']:
    getattr(u, name).argtypes = [W.HWND]
    getattr(u, name).restype = W.BOOL

class RECT(C.Structure):
    _fields_ = [('left', W.LONG), ('top', W.LONG), ('right', W.LONG), ('bottom', W.LONG)]

class GUIINFO(C.Structure):
    _fields_ = [('cbSize', W.DWORD), ('flags', W.DWORD), ('hwndActive', W.HWND), ('hwndFocus', W.HWND), ('hwndCapture', W.HWND), ('hwndMenuOwner', W.HWND), ('hwndMoveSize', W.HWND), ('hwndCaret', W.HWND), ('rcCaret', RECT)]

u.GetGUIThreadInfo.argtypes = [W.DWORD, C.POINTER(GUIINFO)]
rows = []
callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

@callback_type
def callback(hwnd, _):
    title, cls = C.create_unicode_buffer(512), C.create_unicode_buffer(256)
    u.GetWindowTextW(hwnd, title, len(title))
    u.GetClassNameW(hwnd, cls, len(cls))
    pid = W.DWORD()
    tid = u.GetWindowThreadProcessId(hwnd, C.byref(pid))
    visible = bool(u.IsWindowVisible(hwnd))
    row = dict(hwnd=hex(hwnd), pid=pid.value, tid=tid, title=title.value, cls=cls.value, visible=visible, enabled=bool(u.IsWindowEnabled(hwnd)), owner=hex(u.GetWindow(hwnd,4) or 0), popup=hex(u.GetLastActivePopup(hwnd) or 0))
    if visible:
        result = C.c_size_t()
        row['responds'] = bool(u.SendMessageTimeoutW(hwnd, 0, 0, 0, 3, 500, C.byref(result)))
        row['hung'] = bool(u.IsHungAppWindow(hwnd))
        info = GUIINFO(cbSize=C.sizeof(GUIINFO))
        if u.GetGUIThreadInfo(tid, C.byref(info)):
            row['thread_gui'] = {name:hex(getattr(info,name) or 0) for name in ['hwndActive','hwndFocus','hwndCapture','hwndMenuOwner']}
    rows.append(row)
    return True

u.EnumWindows.argtypes = [callback_type, W.LPARAM]
u.EnumWindows(callback, 0)
if '--close-signin' in sys.argv:
    u.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    main = {r['hwnd'] for r in rows if r['cls'] == 'AcrobatSDIWindow'}
    for row in rows:
        if row['cls'] in ('WebviewEmbeddedWB', 'EmbeddedWB') and row['owner'] in main:
            u.PostMessageW(int(row['hwnd'], 16), 0x10, 0, 0)
    time.sleep(2)
    rows.clear()
    u.EnumWindows(callback, 0)
print(json.dumps(dict(foreground=hex(u.GetForegroundWindow() or 0), windows=rows), indent=2))
