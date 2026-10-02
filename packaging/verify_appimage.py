"""Verify a local AppImage, remembering unchanged files in a private user cache."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile


def identity(info):
    # ctime also changes on writes that restore the old size and mtime.
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def private_file(info):
    return (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o022 and info.st_nlink == 1)


@contextmanager
def cache_entry(image, expected, directory):
    """Serialize verification; an unavailable cache never bypasses hashing."""
    lock = None
    entry = None
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise OSError('The verification cache is not private')
        key = hashlib.sha256(os.fsencode(image) + b'\0' + expected.encode()).hexdigest()
        descriptor = os.open(directory / (key + '.lock'),
                             os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        lock = os.fdopen(descriptor, 'a')
        if not private_file(os.fstat(lock.fileno())):
            raise OSError('The verification lock is not private')
        fcntl.flock(lock, fcntl.LOCK_EX)
        entry = directory / (key + '.json')
    except OSError:
        if lock is not None:
            lock.close()
            lock = None
    try:
        yield entry
    finally:
        if lock is not None:
            lock.close()


def cached(entry, record):
    if entry is None:
        return False
    try:
        descriptor = os.open(entry, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as source:
            if not private_file(os.fstat(source.fileno())):
                return False
            return json.loads(source.read(4096)) == record
    except (OSError, ValueError):
        return False


def remember(entry, record):
    if entry is None:
        return
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix='.verified-', dir=entry.parent)
        with os.fdopen(descriptor, 'w') as target:
            json.dump(record, target)
            target.write('\n')
        os.replace(temporary, entry)
    except OSError:
        # A full or unwritable cache affects performance, not verification.
        pass
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass


def verify(image, expected, directory=None, always=False):
    image = Path(os.path.abspath(image))
    if directory is None:
        directory = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'acrobat-wine/verified-appimages'

    def check(entry):
        with image.open('rb') as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError('The AppImage must be a regular file')
            record = {'schema': 1, 'sha256': expected, 'identity': identity(before)}
            hit = cached(entry, record)
            if not hit and hashlib.file_digest(source, 'sha256').hexdigest() != expected:
                raise ValueError(f'The AppImage checksum does not match the configured release: {image}')
            if identity(os.fstat(source.fileno())) != identity(before) or identity(image.stat()) != identity(before):
                raise ValueError('The AppImage changed during verification; try launching it again')
            if not hit:
                remember(entry, record)
            return hit

    if always:
        return check(None)
    with cache_entry(image, expected, Path(directory)) as entry:
        return check(entry)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('sha256')
    parser.add_argument('--always', action='store_true')
    args = parser.parse_args()
    try:
        verify(args.image, args.sha256, always=args.always)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
