#!/usr/bin/env python3
"""Extract the application's bundled Windows icon; do not redraw its artwork."""
from pathlib import Path
import struct
import sys

source, output = map(Path, sys.argv[1:3])
data = source.read_bytes()
pe = struct.unpack_from('<I', data, 60)[0]
optional = pe + 24
directory = optional + (112 if struct.unpack_from('<H', data, optional)[0] == 0x20B else 96)
resource_rva = struct.unpack_from('<I', data, directory + 16)[0]
section_count = struct.unpack_from('<H', data, pe + 6)[0]
section_size = struct.unpack_from('<H', data, pe + 20)[0]
sections = []
for i in range(section_count):
    offset = optional + section_size + i * 40
    size, rva, raw_size, raw = struct.unpack_from('<4I', data, offset + 8)
    sections.append((rva, max(size, raw_size), raw))


def offset(rva):
    return next(raw + rva - base for base, length, raw in sections if base <= rva < base + length)


root = offset(resource_rva)
resources = {}


def walk(relative=0, keys=()):
    position = root + relative
    named, ids = struct.unpack_from('<HH', data, position + 12)
    for i in range(named + ids):
        name, target = struct.unpack_from('<II', data, position + 16 + i * 8)
        if target & 0x80000000:
            walk(target & 0x7fffffff, keys + (name,))
        else:
            rva, size = struct.unpack_from('<II', data, root + target)
            resources[keys + (name,)] = data[offset(rva):offset(rva) + size]


walk()
group = next(value for key, value in resources.items() if key[0] == 14)
count = struct.unpack_from('<H', group, 4)[0]
entries, images = bytearray(), bytearray()
for i in range(count):
    width, height, colors, reserved, planes, bpp, size, identifier = struct.unpack_from('<BBBBHHIH', group, 6 + i * 14)
    image = next(value for key, value in resources.items() if key[:2] == (3, identifier))
    entries += struct.pack('<BBBBHHII', width, height, colors, reserved, planes, bpp,
                           len(image), 6 + 16 * count + len(images))
    images += image
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(struct.pack('<HHH', 0, 1, count) + entries + images)
print(f'Extracted {count} icon sizes to {output}')
