"""Contract checks using hidden test windows; run with Windows Python under Wine."""
import ctypes as C
from ctypes import wintypes as W
import json
import os
import subprocess
import sys

u = C.WinDLL('user32', use_last_error=True)
k = C.WinDLL('kernel32', use_last_error=True)
LRESULT = C.c_ssize_t
wndproc = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
u.DefWindowProcW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
u.DefWindowProcW.restype = LRESULT
u.DestroyWindow.argtypes = [W.HWND]
u.IsWindow.argtypes = [W.HWND]
u.EndTask.argtypes = [W.HWND, W.BOOL, W.BOOL]
u.EndTask.restype = W.BOOL
k.GetModuleHandleW.argtypes = [W.LPCWSTR]
k.GetModuleHandleW.restype = W.HMODULE
child_mode = 'child' in sys.argv

@wndproc
def callback(hwnd, message, wparam, lparam):
    if message == 0x10:
        if not child_mode:
            u.DestroyWindow(hwnd)
        return 0
    return u.DefWindowProcW(hwnd, message, wparam, lparam)

class WNDCLASS(C.Structure):
    _fields_ = [('style',W.UINT),('lpfnWndProc',wndproc),('cbClsExtra',C.c_int),
                ('cbWndExtra',C.c_int),('hInstance',W.HINSTANCE),('hIcon',W.HICON),
                ('hCursor',W.HANDLE),('hbrBackground',W.HBRUSH),
                ('lpszMenuName',W.LPCWSTR),('lpszClassName',W.LPCWSTR)]

u.RegisterClassW.argtypes = [C.POINTER(WNDCLASS)]
u.CreateWindowExW.argtypes = [W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,
                             C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p]
u.CreateWindowExW.restype = W.HWND
instance = k.GetModuleHandleW(None)
name = 'AcrobatWineEndTaskCheck' + str(os.getpid())
wc = WNDCLASS(lpfnWndProc=callback,hInstance=instance,lpszClassName=name)
assert u.RegisterClassW(C.byref(wc)), C.get_last_error()
window = u.CreateWindowExW(0,name,'EndTask contract check',0,0,0,100,100,None,None,instance,None)
assert window, C.get_last_error()

if child_mode:
    print(hex(window), flush=True)
    message = W.MSG()
    while u.GetMessageW(C.byref(message), None, 0, 0) > 0:
        u.TranslateMessage(C.byref(message))
        u.DispatchMessageW(C.byref(message))
else:
    assert u.EndTask(window, False, False), C.get_last_error()
    assert not u.IsWindow(window)
    assert not u.EndTask(None, False, False)
    child = subprocess.Popen([sys.executable,__file__,'child'],stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        child_window = int(child.stdout.readline().strip(),16)
        assert u.IsWindow(child_window)
        assert not u.EndTask(child_window, False, False)
        assert u.IsWindow(child_window)
        assert u.EndTask(child_window, False, True), C.get_last_error()
        assert child.wait(timeout=5) == 0
        assert not u.IsWindow(child_window)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    print(json.dumps({'graceful_close':'passed','invalid_window':'passed',
                      'non_forced_preserves_unresponsive_window':'passed',
                      'forced_close_of_test_child':'passed'}))
