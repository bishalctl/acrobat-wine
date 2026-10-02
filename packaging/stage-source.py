#!/usr/bin/env python3
"""Stage reviewed source, optionally including the local private payload."""
import argparse
from pathlib import Path
import os
import shutil
import tempfile

from source_tree import source_snapshot, write_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only', action='store_true', help='omit private media for checks')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    media = [] if args.source_only else [
        'manifest.json', 'prefix.tar.zst', 'Adobe.Acrobat.2026.u17.x64.Multilingual.iso']
    for name in media:
        if not (root / 'packaging/payload' / name).is_file():
            parser.exit(1, 'Missing private payload. See docs/packaging.md before running prepare.sh.\n')
    snapshot, _ = source_snapshot(root)
    parent = root / 'state/build'
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='package-source-', dir=parent)) / 'source'
    write_snapshot(snapshot, stage)
    for name in media:
        source = root / 'packaging/payload' / name
        destination = stage / 'packaging/payload' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Media is atomically replaced by export; metadata gets its own snapshot.
        if name == 'manifest.json':
            shutil.copy2(source, destination)
        else:
            os.link(source, destination)
    if not args.source_only:
        (root / 'state/package-source-path').write_text(str(stage) + '\n')
    print(stage)


if __name__ == '__main__':
    main()
