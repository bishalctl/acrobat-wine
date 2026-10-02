"""Inspect or message this Wine desktop's controls without changing Linux focus.

Run with the project's embedded Windows Python. Mouse messages are addressed to
one HWND; this utility never moves the pointer or sends global keyboard input.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import time

u = C.WinDLL('user32', use_last_error=True)
callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

class RECT(C.Structure):
    _fields_ = [('left', W.LONG), ('top', W.LONG), ('right', W.LONG), ('bottom', W.LONG)]

def bind(name, args, result):
    fn = getattr(u, name)
    fn.argtypes, fn.restype = args, result
    return fn

bind('GetWindowTextW', [W.HWND, W.LPWSTR, C.c_int], C.c_int)
bind('GetClassNameW', [W.HWND, W.LPWSTR, C.c_int], C.c_int)
bind('GetWindowRect', [W.HWND, C.POINTER(RECT)], W.BOOL)
bind('GetClientRect', [W.HWND, C.POINTER(RECT)], W.BOOL)
bind('GetWindowThreadProcessId', [W.HWND, C.POINTER(W.DWORD)], W.DWORD)
bind('GetDlgCtrlID', [W.HWND], C.c_int)
bind('GetWindowLongPtrW', [W.HWND, C.c_int], C.c_ssize_t)
bind('GetWindow', [W.HWND, W.UINT], W.HWND)
bind('GetParent', [W.HWND], W.HWND)
bind('GetForegroundWindow', [], W.HWND)
bind('IsWindow', [W.HWND], W.BOOL)
bind('IsWindowVisible', [W.HWND], W.BOOL)
bind('IsWindowEnabled', [W.HWND], W.BOOL)
bind('EnumWindows', [callback_type, W.LPARAM], W.BOOL)
bind('EnumChildWindows', [W.HWND, callback_type, W.LPARAM], W.BOOL)
bind('PostMessageW', [W.HWND, W.UINT, W.WPARAM, W.LPARAM], W.BOOL)
bind('MapVirtualKeyW', [W.UINT, W.UINT], W.UINT)
bind('SendMessageTimeoutW', [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT, C.POINTER(C.c_size_t)], W.LPARAM)

def send(hwnd, message, wp=0, lp=0, timeout=500):
    result = C.c_size_t()
    ok = u.SendMessageTimeoutW(hwnd, message, wp, lp, 3, timeout, C.byref(result))
    return bool(ok), result.value

def describe(hwnd):
    title, cls = C.create_unicode_buffer(4096), C.create_unicode_buffer(256)
    u.GetClassNameW(hwnd, cls, len(cls))
    style = u.GetWindowLongPtrW(hwnd, -16)
    if cls.value.lower() == 'edit' and style & 0x20:
        title.value = '[password field]'
    else:
        u.GetWindowTextW(hwnd, title, len(title))
        send(hwnd, 0x0D, len(title), C.addressof(title), 200)
    rect, client, pid = RECT(), RECT(), W.DWORD()
    u.GetWindowRect(hwnd, C.byref(rect))
    u.GetClientRect(hwnd, C.byref(client))
    tid = u.GetWindowThreadProcessId(hwnd, C.byref(pid))
    row = dict(hwnd=hex(hwnd), cls=cls.value, text=title.value,
                id=u.GetDlgCtrlID(hwnd), pid=pid.value, tid=tid,
                visible=bool(u.IsWindowVisible(hwnd)), enabled=bool(u.IsWindowEnabled(hwnd)),
                owner=hex(u.GetWindow(hwnd, 4) or 0), parent=hex(u.GetParent(hwnd) or 0),
                rect=[rect.left, rect.top, rect.right, rect.bottom],
                client=[client.left, client.top, client.right, client.bottom])
    if cls.value.lower() == 'button' and (style & 0xF) in [2, 3, 4, 5, 6, 9]:
        ok, state = send(hwnd, 0x00F0, timeout=200)  # BM_GETCHECK
        row['check_state'] = state if ok else None
    return row

parser = argparse.ArgumentParser()
parser.add_argument('--click', type=lambda n: int(n, 0))
parser.add_argument('--close', type=lambda n: int(n, 0))
parser.add_argument('--mouse', nargs=3, metavar=('HWND', 'X', 'Y'))
parser.add_argument('--command', nargs=2, metavar=('HWND', 'ID'))
parser.add_argument('--text', nargs=2, metavar=('HWND', 'TEXT'))
parser.add_argument('--chars', nargs=2, metavar=('HWND', 'TEXT'))
parser.add_argument('--key', nargs=2, metavar=('HWND', 'VK'))
args = parser.parse_args()
if args.click is not None:
    assert u.IsWindow(args.click) and u.IsWindowEnabled(args.click), 'Invalid or disabled target'
    assert u.PostMessageW(args.click, 0x00F5, 0, 0), 'BM_CLICK failed'
elif args.close is not None:
    assert u.IsWindow(args.close), 'Invalid target'
    assert u.PostMessageW(args.close, 0x10, 0, 0), 'WM_CLOSE failed'
elif args.mouse:
    hwnd, x, y = (int(n, 0) for n in args.mouse)
    assert u.IsWindow(hwnd) and u.IsWindowEnabled(hwnd), 'Invalid or disabled target'
    rect = RECT()
    u.GetClientRect(hwnd, C.byref(rect))
    assert 0 <= x < rect.right and 0 <= y < rect.bottom, 'Point outside target control'
    point = (y << 16) | (x & 0xffff)
    for message, button in [(0x200, 0), (0x201, 1), (0x202, 0)]:
        assert u.PostMessageW(hwnd, message, button, point), 'Mouse message failed'
elif args.command:
    hwnd, command = (int(n, 0) for n in args.command)
    assert u.IsWindow(hwnd) and u.IsWindowEnabled(hwnd), 'Invalid or disabled target'
    assert u.PostMessageW(hwnd, 0x111, command, 0), 'WM_COMMAND failed'
elif args.text:
    hwnd = int(args.text[0], 0)
    assert u.IsWindow(hwnd) and u.IsWindowEnabled(hwnd), 'Invalid or disabled target'
    value = C.create_unicode_buffer(args.text[1])
    assert send(hwnd, 0x0C, 0, C.addressof(value))[0], 'WM_SETTEXT failed'
elif args.chars:
    hwnd = int(args.chars[0], 0)
    assert u.IsWindow(hwnd) and u.IsWindowEnabled(hwnd), 'Invalid or disabled target'
    encoded = args.chars[1].encode('utf-16-le')
    for index in range(0, len(encoded), 2):
        value = int.from_bytes(encoded[index:index + 2], 'little')
        assert u.PostMessageW(hwnd, 0x102, value, 1), 'WM_CHAR failed'
elif args.key:
    hwnd, key = (int(value, 0) for value in args.key)
    assert u.IsWindow(hwnd) and u.IsWindowEnabled(hwnd), 'Invalid or disabled target'
    assert key in [8, 9, 13, 27, 33, 34, 35, 36, 37, 38, 39, 40, 45, 46], 'Only navigation/edit keys are allowed'
    flags = 1 | (u.MapVirtualKeyW(key, 0) << 16)
    if key in [33, 34, 35, 36, 37, 38, 39, 40, 45, 46]:
        flags |= 1 << 24
    assert u.PostMessageW(hwnd, 0x100, key, flags), 'WM_KEYDOWN failed'
    assert u.PostMessageW(hwnd, 0x101, key, flags | (3 << 30)), 'WM_KEYUP failed'
else:
    windows = []
    @callback_type
    def top(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        row = describe(hwnd)
        row['children'] = []
        @callback_type
        def child(handle, _):
            row['children'].append(describe(handle))
            return True
        u.EnumChildWindows(hwnd, child, 0)
        windows.append(row)
        return True
    u.EnumWindows(top, 0)
    print(json.dumps(dict(foreground=hex(u.GetForegroundWindow() or 0), windows=windows), indent=2))
