#!/usr/bin/env python3
"""Export this installed application as a deterministic, private prefix seed.

The live prefix is read only. Documents, browser sessions, caches, temporary
files, recent-file lists, and links into the exporting user's home are omitted.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile

EXPECTED_ACROBAT_SHA256 = 'b4b6e679c69679091ca70fdfe847850943b729c1a5b21e179bc080a538454621'


def clean_registry(data):
    text = data.decode('utf-8')
    blocks = re.split(r'(?=^\[)', text, flags=re.M)
    private = ('\\\\cRecentFiles', '\\\\cRecentFolders', '\\\\ComDlg32',
               '\\\\RecentDocs', '\\\\TypedPaths', '\\\\WordWheelQuery',
               '\\\\SessionManagement', '\\\\Wine\\\\Fonts\\\\External Fonts')
    cleaned = []
    for block in blocks:
        key = block.split('\n', 1)[0]
        if any(part in key for part in private):
            continue
        if '\\\\Fonts]' in key:
            # Wine regenerates host font registrations. Keep installed Windows
            # fonts, not cache entries pointing into the exporting machine.
            block = '\n'.join(line for line in block.split('\n')
                              if not re.search(r'="[Zz]:', line))
        cleaned.append(block)
    return ''.join(cleaned).encode()


def export(prefix, output):
    prefix = prefix.resolve()
    executable = prefix / 'drive_c/Program Files/Adobe/Acrobat DC/Acrobat/Acrobat.exe'
    if not executable.is_file() or not (prefix / 'system.reg').is_file():
        raise SystemExit('Expected an installed Acrobat Wine prefix.')
    with executable.open('rb') as source:
        executable_digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if executable_digest != EXPECTED_ACROBAT_SHA256:
        raise SystemExit('The application differs from the verified ISO installation; export stopped.')
    users = [p.name for p in (prefix / 'drive_c/users').iterdir()
             if p.is_dir() and p.name.lower() not in ('public', 'default', 'default user')]
    if len(users) != 1:
        raise SystemExit(f'Expected one Windows user profile, found {users!r}.')
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / '.prefix.tar.zst.partial'
    final = output / 'prefix.tar.zst'
    excluded = []
    total = count = 0

    def include(relative):
        low = relative.as_posix().lower()
        parts = relative.parts
        if parts[0] == 'dosdevices':
            return False  # Recreate C:, H:, and Z: for the launching user.
        if low.startswith('drive_c/windows/temp'):
            return False
        if len(parts) >= 4 and parts[:2] == ('drive_c', 'users'):
            if parts[3] != 'AppData':
                return False
        if any(s in low for s in ['/appdata/local/temp', '/appdata/local/adobe/acrocef',
                                 '/appdata/local/crashdumps']):
            return False
        if relative.suffix.lower() in ('.log', '.dmp', '.mdmp'):
            return False
        return True

    with temporary.open('wb') as destination:
        compressor = subprocess.Popen(['zstd', '-q', '-T2', '-6', '-c'],
                                      stdin=subprocess.PIPE, stdout=destination)
        try:
            with tarfile.open(fileobj=compressor.stdin, mode='w|',
                              format=tarfile.PAX_FORMAT) as archive:
                for parent, directories, files in os.walk(prefix, followlinks=False):
                    directories.sort()
                    files.sort()
                    for name in list(directories) + files:
                        path = Path(parent) / name
                        relative = path.relative_to(prefix)
                        if not include(relative) or path.is_symlink():
                            if name in directories:
                                directories.remove(name)
                            excluded.append(relative.as_posix())
                            continue
                        before = path.stat()
                        if not (stat.S_ISREG(before.st_mode) or stat.S_ISDIR(before.st_mode)):
                            continue
                        info = archive.gettarinfo(str(path), arcname=relative.as_posix())
                        info.uid = info.gid = info.mtime = 0
                        info.uname = info.gname = ''
                        info.mode = 0o755 if info.isdir() else 0o644
                        if info.isdir():
                            archive.addfile(info)
                        elif relative.name in ('user.reg', 'userdef.reg', 'system.reg') and len(relative.parts) == 1:
                            data = clean_registry(path.read_bytes())
                            info.size = len(data)
                            archive.addfile(info, io.BytesIO(data))
                        else:
                            with path.open('rb') as source:
                                archive.addfile(info, source)
                            after = path.stat()
                            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                                raise RuntimeError(f'File changed during export; retry: {relative}')
                        total += info.size
                        count += 1
            compressor.stdin.close()
            if compressor.wait() != 0:
                raise RuntimeError('Prefix compression failed.')
        except BaseException:
            compressor.kill()
            compressor.wait()
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(final)
    with final.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    manifest = {
        'schema': 1,
        'application': 'Adobe Acrobat',
        'application_version': '26.002.21931',
        'wine_version': '11.18',
        'architecture': 'x86_64',
        'source_windows_user': users[0],
        'archive': final.name,
        'archive_sha256': digest,
        'archive_bytes': final.stat().st_size,
        'unpacked_bytes': total,
        'entries': count,
        'acrobat_exe_sha256': executable_digest,
        'excluded': ['personal folders', 'browser profile and cookies', 'temporary files',
                     'crash/log files', 'recent-file/folder lists', 'external symlinks'],
    }
    manifest_path = output / '.manifest.json.partial'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    manifest_path.replace(output / 'manifest.json')
    (output / 'excluded-files.txt').write_text('\n'.join(excluded) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, default=Path('prefix'))
    parser.add_argument('--output', type=Path, default=Path('packaging/payload'))
    args = parser.parse_args()
    export(args.prefix, args.output)
