#!/usr/bin/env python3
"""Capture one X11 window's backing pixmap without focusing or moving it."""
import ctypes as C
import ctypes.util
import os
from pathlib import Path
import struct
import sys
import zlib

library = C.util.find_library('Xcomposite')
if not library:
    library = next((str(p) for root in Path('/nix/store').glob('*-libXcomposite-*')
                    if root.is_dir() for p in (root/'lib').glob('libXcomposite.so.1*')), None)
if not library:
    sys.exit('libXcomposite is required.')
x = C.CDLL(library)
display_type = C.c_void_p
drawable_type = C.c_ulong

class XImage(C.Structure):
    _fields_ = [('width',C.c_int),('height',C.c_int),('xoffset',C.c_int),('format',C.c_int),
                ('data',C.c_void_p),('byte_order',C.c_int),('bitmap_unit',C.c_int),
                ('bitmap_bit_order',C.c_int),('bitmap_pad',C.c_int),('depth',C.c_int),
                ('bytes_per_line',C.c_int),('bits_per_pixel',C.c_int),
                ('red_mask',C.c_ulong),('green_mask',C.c_ulong),('blue_mask',C.c_ulong)]

x.XOpenDisplay.argtypes=[C.c_char_p];x.XOpenDisplay.restype=display_type
x.XCompositeNameWindowPixmap.argtypes=[display_type,drawable_type]
x.XCompositeNameWindowPixmap.restype=drawable_type
x.XGetGeometry.argtypes=[display_type,drawable_type,C.POINTER(drawable_type),
                         C.POINTER(C.c_int),C.POINTER(C.c_int),C.POINTER(C.c_uint),
                         C.POINTER(C.c_uint),C.POINTER(C.c_uint),C.POINTER(C.c_uint)]
x.XGetImage.argtypes=[display_type,drawable_type,C.c_int,C.c_int,C.c_uint,C.c_uint,C.c_ulong,C.c_int]
x.XGetImage.restype=C.POINTER(XImage)
x.XDestroyImage.argtypes=[C.POINTER(XImage)]
x.XFreePixmap.argtypes=[display_type,drawable_type]
x.XCloseDisplay.argtypes=[display_type]

if len(sys.argv)!=3:
    sys.exit('Usage: capture-window.py X11_WINDOW_ID output.png')
display=x.XOpenDisplay(os.environ.get('DISPLAY',':0').encode())
if not display:
    sys.exit('Cannot connect to the X display.')
pixmap=x.XCompositeNameWindowPixmap(display,int(sys.argv[1],0))
root=drawable_type();left=C.c_int();top=C.c_int()
width=C.c_uint();height=C.c_uint();border=C.c_uint();depth=C.c_uint()
if not x.XGetGeometry(display,pixmap,C.byref(root),C.byref(left),C.byref(top),C.byref(width),C.byref(height),C.byref(border),C.byref(depth)):
    sys.exit('Cannot read the window pixmap.')
image=x.XGetImage(display,pixmap,0,0,width,height,C.c_ulong(-1),2)
if not image:
    sys.exit('Cannot capture the window pixmap.')
try:
    info=image.contents
    if info.bits_per_pixel!=32 or info.byte_order!=0:
        sys.exit('Unsupported X image format.')
    w,h=info.width,info.height
    data=C.string_at(info.data,info.bytes_per_line*h)
    pixels=b''.join(data[row*info.bytes_per_line:row*info.bytes_per_line+w*4] for row in range(h))
    rgb=bytearray(w*h*3)
    rgb[0::3]=pixels[2::4];rgb[1::3]=pixels[1::4];rgb[2::3]=pixels[0::4]
    raw=b''.join(b'\x00'+rgb[row*w*3:(row+1)*w*3] for row in range(h))
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'
    png+=chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))
    png+=chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
    Path(sys.argv[2]).write_bytes(png)
    print(f'Captured {w}x{h} without changing focus: {sys.argv[2]}')
finally:
    x.XDestroyImage(image)
    x.XFreePixmap(display,pixmap)
    x.XCloseDisplay(display)
