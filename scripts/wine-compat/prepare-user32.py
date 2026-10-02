#!/usr/bin/env python3
"""Forward Wine 11.18's unimplemented EndTask export to our compatibility DLL.

Only a project-local copy is written. All other exports and executable code are
preserved. A native override is required to load this copy rather than the
immutable Nix-store builtin. The change is limited to Acrobat's Wine profile.
"""
from pathlib import Path
import hashlib
import json
import struct
import sys

source, target = map(Path, sys.argv[1:3])
data = bytearray(source.read_bytes())
source_hash = hashlib.sha256(data).hexdigest()
expected = '9304ff56ab3b1ca5d08dca51e89c1737359dcf09c2dce17e84396f9c2518919e'
if source_hash != expected:
    sys.exit('Unsupported user32.dll: expected the verified Nix Wine Staging 11.18 x64 build.')

pe = struct.unpack_from('<I', data, 60)[0]
optional = pe + 24
optional_size = struct.unpack_from('<H', data, pe + 20)[0]
assert struct.unpack_from('<H', data, optional)[0] == 0x20b
sections = []
for index in range(struct.unpack_from('<H', data, pe + 6)[0]):
    header = optional + optional_size + index * 40
    virtual_size, rva, raw_size, raw_offset = struct.unpack_from('<4I', data, header + 8)
    sections.append((header, virtual_size, rva, raw_size, raw_offset))

def offset(rva):
    for _, virtual_size, address, raw_size, raw_offset in sections:
        if address <= rva < address + max(virtual_size, raw_size):
            return raw_offset + rva - address
    raise ValueError(f'Unmapped RVA: {rva:#x}')

export_rva, export_size = struct.unpack_from('<II', data, optional + 112)
fields = struct.unpack_from('<IIHH7I', data, offset(export_rva))
function_table, name_table, ordinal_table = map(offset, fields[8:11])
entry = None
for index in range(fields[7]):
    name_offset = offset(struct.unpack_from('<I', data, name_table + index * 4)[0])
    name = bytes(data[name_offset:data.index(0, name_offset)])
    if name == b'EndTask':
        ordinal = struct.unpack_from('<H', data, ordinal_table + index * 2)[0]
        entry = function_table + ordinal * 4
        break
assert entry is not None, 'Missing EndTask export'
original_entry = struct.unpack_from('<I', data, entry)[0]
forwarder = b'wine_endtask.EndTask\0'
forward_rva = export_rva + export_size
forward_offset = offset(forward_rva)
section = next(s for s in sections if s[2] <= forward_rva < s[2] + s[3])
assert forward_offset + len(forwarder) <= section[4] + section[3]
assert not any(data[forward_offset:forward_offset + len(forwarder)]), 'No unused export padding'
data[forward_offset:forward_offset + len(forwarder)] = forwarder
struct.pack_into('<I', data, entry, forward_rva)
struct.pack_into('<I', data, optional + 116, export_size + len(forwarder))
struct.pack_into('<I', data, section[0] + 8, max(section[1], forward_rva - section[2] + len(forwarder)))

# Wine's marker redirects a builtin copy back to its Nix-store original.
marker = b'Wine builtin DLL\0'
assert data[64:64 + len(marker)] == marker
data[64:64 + len(marker)] = bytes(len(marker))
struct.pack_into('<I', data, optional + 64, 0)  # clear the now-stale PE checksum
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(data)
target.with_suffix('.json').write_text(json.dumps({
    'wine_version': '11.18', 'architecture': 'x64',
    'source': str(source), 'source_sha256': source_hash,
    'output_sha256': hashlib.sha256(data).hexdigest(),
    'export': 'EndTask', 'original_rva': hex(original_entry),
    'forward_to': 'wine_endtask.EndTask',
}, indent=2) + '\n')
print(target)
