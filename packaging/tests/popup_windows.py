"""Wine integration probe: print XIDs, keep windows alive until stdin closes.

Run using Windows Python on a private display. Query override_redirect for the
returned XIDs from the Linux test process; no compositor-specific rules apply.
"""
import ctypes as C
from ctypes import wintypes as W
import json
import sys
import threading
import time

u = C.WinDLL('user32', use_last_error=True)
k = C.WinDLL('kernel32', use_last_error=True)
WNDPROC = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)


class WNDCLASS(C.Structure):
    _fields_ = [('style', W.UINT), ('wndproc', WNDPROC), ('class_extra', C.c_int),
                ('window_extra', C.c_int), ('instance', W.HINSTANCE), ('icon', W.HICON),
                ('cursor', W.HANDLE), ('background', W.HBRUSH),
                ('menu', W.LPCWSTR), ('name', W.LPCWSTR)]


def bind(dll, name, args, result):
    function = getattr(dll, name)
    function.argtypes, function.restype = args, result
    return function


bind(k, 'GetModuleHandleW', [W.LPCWSTR], W.HMODULE)
bind(u, 'DefWindowProcW', [W.HWND, W.UINT, W.WPARAM, W.LPARAM], C.c_ssize_t)
bind(u, 'RegisterClassW', [C.POINTER(WNDCLASS)], W.ATOM)
bind(u, 'CreateWindowExW', [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
    C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID], W.HWND)
bind(u, 'ShowWindow', [W.HWND, C.c_int], W.BOOL)
bind(u, 'SetLayeredWindowAttributes', [W.HWND, W.DWORD, W.BYTE, W.DWORD], W.BOOL)
bind(u, 'GetPropW', [W.HWND, W.LPCWSTR], W.HANDLE)
bind(u, 'PeekMessageW', [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL)
bind(u, 'TranslateMessage', [C.POINTER(W.MSG)], W.BOOL)
bind(u, 'DispatchMessageW', [C.POINTER(W.MSG)], C.c_ssize_t)
bind(u, 'DestroyWindow', [W.HWND], W.BOOL)
wndproc = WNDPROC(u.DefWindowProcW)
instance = k.GetModuleHandleW(None)
for name in ['AcrobatPopupProbeMain', 'AVL_AVWindow', 'UnrelatedPopupClass']:
    wc = WNDCLASS(wndproc=wndproc, instance=instance, name=name)
    assert u.RegisterClassW(C.byref(wc)), C.get_last_error()

windows = []
rows = []


def window(name, cls, style, ex_style, owner, expected_popup):
    hwnd = u.CreateWindowExW(ex_style, cls, name, style, 50, 50, 240, 140,
                             owner, None, instance, None)
    assert hwnd, (name, C.get_last_error())
    windows.append(hwnd)
    if ex_style & 0x80000:
        assert u.SetLayeredWindowAttributes(hwnd, 0, 255, 2)
    u.ShowWindow(hwnd, 5)  # SW_SHOW activates and used to promote coachmarks.
    rows.append({'name': name, 'xid': u.GetPropW(hwnd, '__wine_x11_whole_window'),
                 'expected_override_redirect': expected_popup})
    return hwnd


parent = window('document', 'AcrobatPopupProbeMain', 0xcf0000, 0, None, False)
popup, layered = 0x86000000, 0x80000
window('owned Acrobat coachmark', 'AVL_AVWindow', popup, layered, parent, True)
window('unrelated layered popup', 'UnrelatedPopupClass', popup, layered, parent, False)
window('captioned Acrobat window', 'AVL_AVWindow', popup | 0xc00000, layered, parent, False)
window('resizable Acrobat window', 'AVL_AVWindow', popup | 0x40000, layered, parent, False)
window('standalone Acrobat window', 'AVL_AVWindow', popup, layered, None, False)
window('Acrobat tool palette', 'AVL_AVWindow', popup, layered | 0x80, parent, False)
window('Acrobat modal frame', 'AVL_AVWindow', popup, layered | 1, parent, False)
window('Acrobat application window', 'AVL_AVWindow', popup, layered | 0x40000, parent, False)
window('non-layered Acrobat popup', 'AVL_AVWindow', popup, 0, parent, False)
window('standard dialog', '#32770', popup | 0xc00000, 1, parent, False)

print(json.dumps(rows), flush=True)
stop = threading.Event()
threading.Thread(target=lambda: (sys.stdin.read(), stop.set()), daemon=True).start()
deadline = time.monotonic() + 30
message = W.MSG()
while not stop.is_set() and time.monotonic() < deadline:
    while u.PeekMessageW(C.byref(message), None, 0, 0, 1):
        u.TranslateMessage(C.byref(message))
        u.DispatchMessageW(C.byref(message))
    time.sleep(.01)
for hwnd in reversed(windows):
    u.DestroyWindow(hwnd)
