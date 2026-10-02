"""Map the launching user's filesystem without changing Unix permissions."""
import json
import os
from pathlib import Path
import pwd
import sys


def replace_link(path, target):
    if path.is_symlink():
        if os.readlink(path) == str(target):
            return
        path.unlink()
    elif path.exists():
        raise RuntimeError(f'Refusing to replace a real file or directory: {path}')
    path.symlink_to(target, target_is_directory=True)


def configure(prefix, home=None):
    prefix = Path(prefix)
    home = Path(home or Path.home()).resolve()
    devices = prefix / 'dosdevices'
    devices.mkdir(parents=True, exist_ok=True)
    replace_link(devices / 'c:', '../drive_c')
    replace_link(devices / 'z:', '/')
    replace_link(devices / 'h:', home)
    username = pwd.getpwuid(os.getuid()).pw_name
    user = prefix / 'drive_c/users' / username
    # Keep nonempty Windows folders intact. H: always exposes the Linux home.
    for name in ['Desktop', 'Documents', 'Downloads', 'Music', 'Pictures', 'Videos', 'Templates']:
        path = user / name
        target = home / name
        if not target.is_dir():
            target = home
        if path.is_dir() and not path.is_symlink():
            try:
                path.rmdir()  # Succeeds only for an empty directory.
            except OSError:
                continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or not path.exists():
            replace_link(path, target)
    return {'root': 'Z:\\', 'home': 'H:\\', 'unix_home': str(home),
            'unix_uid': os.getuid(), 'permissions': 'unchanged'}


if __name__ == '__main__':
    print(json.dumps(configure(sys.argv[1]), indent=2))
