#!/usr/bin/env python3
"""Read Acrobat's product version without starting Wine."""

import struct
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
executable = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else root / "prefix/drive_c/Program Files/Adobe/Acrobat DC/Acrobat/Acrobat.exe"
)
try:
    data = executable.read_bytes()
except FileNotFoundError:
    sys.exit("Acrobat is not installed in this project's prefix.")

# VS_FIXEDFILEINFO starts with a fixed signature and structure version.
signature = struct.pack("<II", 0xFEEF04BD, 0x00010000)
offset = data.find(signature)
if offset < 0 or offset + 52 > len(data):
    sys.exit(f"No Windows version resource found in {executable}")
fields = struct.unpack_from("<13I", data, offset)
product_ms, product_ls = fields[4:6]
print(f"{product_ms >> 16}.{product_ms & 0xffff:03d}.{product_ls >> 16}")
