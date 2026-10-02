#!/usr/bin/env python3
"""Audit and export the reviewed source for Acrobat on Wine packaging."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess

MANIFEST = 'packaging/source-files.txt'
MAX_FILE_BYTES = 1024 * 1024
SOURCE_SUFFIXES = {'.md', '.nix', '.lock', '.py', '.sh', '.c', '.h', '.def',
                   '.patch', '.reg', '.lua', '.txt', '.svg'}
SPECIAL_FILES = {'.gitignore', 'acrobat', 'winecfg'}
PRIVATE_PARTS = {'.git', '.local', '.agents', '.codex', '.claude', '.opencode',
                 '.ssh', '.gnupg', 'prefix', 'payload', 'state', 'logs', 'dist',
                 'drive_c', 'dosdevices', '__pycache__'}
CONTENT_CHECKS = {
    'private key': re.compile(r'-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----'),
    'GitHub token': re.compile(r'\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}\b'),
    'AWS access key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'Slack token': re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b'),
    'credential assignment': re.compile(
        r'''(?i)["']?(?:api_key|access_token|client_secret|password)["']?\s*[:=]\s*["'][A-Za-z0-9_+/=-]{20,}["']'''),
    'local home path': re.compile(r'/(?:home|Users)/[A-Za-z0-9_.-]+(?:/|\b)'),
}


def visible_sources(root):
    """Use project ignore rules; also catch tracked files that ignore rules hide."""
    command = ['rg', '--files', '--hidden', '--null', '--no-ignore-parent',
               '--no-ignore-global', '--no-ignore-dot', '--no-require-git',
               '--glob', '!.git', '--glob', '!.git/**']
    result = subprocess.run(command, cwd=root, capture_output=True, check=True)
    visible = {os.fsdecode(path) for path in result.stdout.split(b'\0') if path}
    index_checked = False
    if shutil.which('git'):
        top = subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'],
                             capture_output=True, text=True)
        if top.returncode == 0 and Path(top.stdout.strip()).resolve() == root.resolve():
            tracked = subprocess.run(['git', '-C', str(root), 'ls-files', '--cached', '-z'],
                                     capture_output=True, check=True)
            visible.update(os.fsdecode(path) for path in tracked.stdout.split(b'\0') if path)
            index_checked = True
    return visible, index_checked


def source_snapshot(root, *, check_tree=True):
    root = Path(root).resolve()
    names = [line.strip() for line in (root / MANIFEST).read_text().splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    if not names or len(names) != len(set(names)) or MANIFEST not in names:
        raise ValueError('The source list must include itself and contain unique paths.')
    snapshot = []
    for name in names:
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '..' in relative.parts or '\\' in name
                or relative.as_posix() != name):
            raise ValueError(f'Invalid source path: {name}')
        if any(part.lower() in PRIVATE_PARTS for part in relative.parts):
            raise ValueError(f'Private path cannot be exported: {name}')
        if name not in SPECIAL_FILES and relative.suffix.lower() not in SOURCE_SUFFIXES:
            raise ValueError(f'Not an allowed source file type: {name}')
        source = root
        for part in relative.parts:
            source /= part
            if source.is_symlink():
                raise ValueError(f'Symlink cannot be exported: {name}')
        info = source.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            raise ValueError(f'Not a small regular source file: {name}')
        data = source.read_bytes()
        try:
            content = data.decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError(f'Binary or non-UTF-8 source: {name}') from error
        if any(ord(char) < 32 and char not in '\t\n\r' for char in content):
            raise ValueError(f'Binary control bytes in source: {name}')
        for label, pattern in CONTENT_CHECKS.items():
            if pattern.search(content):
                # Report the kind and filename, never the suspected secret itself.
                raise ValueError(f'Possible {label} in {name}; review before exporting.')
        mode = 0o755 if info.st_mode & 0o111 else 0o644
        snapshot.append((name, data, mode))
    index_checked = False
    if check_tree:
        visible, index_checked = visible_sources(root)
        unexpected = visible - set(names)
        hidden = set(names) - visible
        if unexpected:
            raise ValueError('Unreviewed visible or tracked files: ' + ', '.join(sorted(unexpected)))
        if hidden:
            raise ValueError('Listed source files are hidden by ignore rules: ' + ', '.join(sorted(hidden)))
    return snapshot, index_checked


def write_snapshot(snapshot, destination):
    """Write only already-audited bytes, without copying metadata or symlinks."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for name, data, mode in snapshot:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as file:
            file.write(data)
        target.chmod(mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true', help='audit without exporting')
    action.add_argument('--output', type=Path, help='create a new source-only directory')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        snapshot, index_checked = source_snapshot(root)
        if args.output:
            write_snapshot(snapshot, args.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Source audit failed: {error}\n')
    print(json.dumps({'files': len(snapshot), 'bytes': sum(len(item[1]) for item in snapshot),
                      'git_index_checked': index_checked, 'git_history_checked': False,
                      'export': str(args.output) if args.output else None}, indent=2))


if __name__ == '__main__':
    main()
