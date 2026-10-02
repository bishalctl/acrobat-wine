#!/usr/bin/env python3
"""Desktop launcher for the personal Acrobat on Wine Nix package and AppImage."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import unquote, urlparse

from host_files import configure as configure_host_files
from native_file_chooser import NativeFileChooser
from supervise import Log, graphics_info, run

HERE = Path(__file__).resolve().parent


def data_paths():
    home = Path.home()
    data = Path(os.environ.get('ACROBAT_DATA_HOME',
                str(Path(os.environ.get('XDG_DATA_HOME', home / '.local/share')) / 'acrobat-wine')))
    state = Path(os.environ.get('ACROBAT_STATE_HOME',
                 str(Path(os.environ.get('XDG_STATE_HOME', home / '.local/state')) / 'acrobat-wine')))
    return data.resolve(), state.resolve()


def registry_string(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def personalize(prefix, source_user):
    username = pwd.getpwuid(os.getuid()).pw_name
    old = prefix / 'drive_c/users' / source_user
    new = prefix / 'drive_c/users' / username
    if source_user != username and old.exists():
        if new.exists():
            raise RuntimeError(f'The template contains two profiles for {username}.')
        old.rename(new)
    for name in ['user.reg', 'userdef.reg', 'system.reg']:
        path = prefix / name
        text = path.read_text()
        old_path = f'C:\\\\users\\\\{source_user}'
        new_path = f'C:\\\\users\\\\{username}'
        text = re.sub(re.escape(old_path), lambda match: new_path, text, flags=re.I)
        path.write_text(text)
    # Acrobat's 'Your computer' view gets explicit local-folder shortcuts.
    registry = prefix / 'user.reg'
    text = registry.read_text()
    key = r'Software\\Adobe\\Adobe Acrobat\\DC\\AVGeneral\\cRecentFolders'
    for index, (label, location) in enumerate([('Linux home', '/H/'), ('Linux filesystem (/)', '/Z/')], 1):
        encoded = ','.join(f'{byte:02x}' for byte in (location + '\0').encode())
        text += (f'\n[{key}\\\\c{index}]\n"aFS"="DOS"\n"sDI"=hex:{encoded}\n'
                 f'"tDisplayText"={registry_string(label)}\n'
                 f'"tDIText"={registry_string(location)}\n')
    registry.write_text(text)
    configure_host_files(prefix)


def initialize(config, data, log):
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    prefix = data / 'prefix'
    marker = data / 'profile.json'
    with (data / 'initialize.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if marker.exists():
            saved = json.loads(marker.read_text())
            if saved.get('schema') != 1 or saved.get('application_version') != config['version']:
                raise RuntimeError('Existing profile belongs to a different package version; it was left intact.')
            executable = prefix / 'drive_c/Program Files/Adobe/Acrobat DC/Acrobat/Acrobat.exe'
            if not executable.is_file():
                raise RuntimeError(f'Existing profile is incomplete: {prefix}')
            return prefix
        if prefix.exists():
            raise RuntimeError(f'An unrecognized profile already exists at {prefix}; it was left intact.')
        manifest = json.loads(Path(config['manifest']).read_text())
        archive = Path(config['archive'])
        log.write('Preparing the installed Acrobat profile for this user.', event='initialize')
        with archive.open('rb') as source:
            actual = hashlib.file_digest(source, 'sha256').hexdigest()
        if actual != manifest['archive_sha256']:
            raise RuntimeError('The bundled profile archive failed its SHA-256 check.')
        if shutil.disk_usage(data).free < manifest['unpacked_bytes'] + 512 * 1024 * 1024:
            raise RuntimeError('Insufficient disk space to prepare the Acrobat profile (about 4.5 GB needed).')
        staging = Path(tempfile.mkdtemp(prefix='.initialize-', dir=data))
        try:
            decompressor = subprocess.Popen([config['zstd'], '-dc', str(archive)], stdout=subprocess.PIPE)
            try:
                with tarfile.open(fileobj=decompressor.stdout, mode='r|') as tar:
                    tar.extractall(staging, filter='data')
                decompressor.stdout.close()
                if decompressor.wait() != 0:
                    raise RuntimeError('Profile decompression failed.')
            except BaseException:
                decompressor.kill()
                decompressor.wait()
                raise
            personalize(staging, manifest['source_windows_user'])
            staging.rename(prefix)
            record = {'schema': 1, 'application_version': config['version'],
                      'wine_version': config['wine_version'],
                      'seed_sha256': actual, 'unix_uid': os.getuid()}
            temporary = data / '.profile.json.tmp'
            temporary.write_text(json.dumps(record, indent=2) + '\n')
            temporary.replace(marker)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        log.write(f'Profile ready: {prefix}', event='initialize')
    return prefix


def windows_argument(argument):
    if argument.startswith('file:'):
        parsed = urlparse(argument)
        if parsed.netloc not in ('', 'localhost'):
            raise ValueError('Only local file:// URLs are supported.')
        argument = unquote(parsed.path)
    if Path(argument).exists():
        return 'Z:' + str(Path(argument).resolve()).replace('/', '\\')
    return argument


def main():
    config = json.loads((HERE / 'runtime.json').read_text())
    parser = argparse.ArgumentParser(description='Acrobat v26.2.21931 x64 Multilingual with Wine.')
    parser.add_argument('--version', action='store_true', help='show bundled versions')
    parser.add_argument('--diagnostics', action='store_true', help='show paths and graphics availability')
    parser.add_argument('--initialize', action='store_true', help='prepare the user profile without opening Acrobat')
    parser.add_argument('--extract-iso', type=Path, metavar='DESTINATION', help='copy the bundled original ISO')
    parser.add_argument('files', nargs='*', help='PDF paths or local file:// URLs')
    args = parser.parse_args()
    if args.version:
        print(f'Acrobat {config["version"]}; Wine Staging {config["wine_version"]}; x86_64 Multilingual')
        return 0
    data, state = data_paths()
    if args.diagnostics:
        print(json.dumps({'application_version': config['version'], 'wine_version': config['wine_version'],
                          'wine': config['wine'], 'profile': str(data / 'prefix'),
                          'profile_initialized': (data / 'profile.json').exists(),
                          'log': str(state / 'logs/acrobat.log'),
                          'journal': 'journalctl --user -t acrobat-wine -b',
                          'gpu_disabled_by_launcher': False,
                          'native_open_dialog': 'desktop portal (Wine fallback)',
                          'root_drive': 'Z:\\', 'home_drive': 'H:\\',
                          'original_iso_bundled': True, 'graphics': graphics_info()}, indent=2))
        return 0
    if args.extract_iso:
        destination = args.extract_iso.expanduser()
        if destination.is_dir():
            destination /= Path(config['iso']).name
        # Never overwrite an existing ISO or other file.
        with destination.open('xb') as out, Path(config['iso']).open('rb') as source:
            shutil.copyfileobj(source, out, length=1024 * 1024)
        print(destination)
        return 0
    log_path = state / 'logs/acrobat.log'
    log = Log(log_path)
    try:
        prefix = initialize(config, data, log)
        mapping = configure_host_files(prefix)
        log.write(json.dumps(mapping), event='filesystem')
        if args.initialize:
            print(prefix)
            return 0
        os.environ['WINEPREFIX'] = str(prefix)
        os.environ['WINEARCH'] = 'win64'
        os.environ['WINEDEBUG'] = os.environ.get('WINEDEBUG', '-all,err+all,warn+seh,+timestamp,+debugstr')
        overrides = 'winemenubuilder.exe=d;adobearm.exe,adobearmhelper.exe,armsvc.exe=d'
        if os.environ.get('WINEDLLOVERRIDES'):
            overrides += ';' + os.environ['WINEDLLOVERRIDES']
        os.environ['WINEDLLOVERRIDES'] = overrides
        executable = prefix / 'drive_c/Program Files/Adobe/Acrobat DC/Acrobat/Acrobat.exe'
        command = [config['wine'], str(executable)] + [windows_argument(a) for a in args.files]
        with NativeFileChooser(state / 'run', prefix, log):
            if sys.stderr.isatty():
                print('Acrobat: starting (Ctrl+C to stop).', file=sys.stderr, flush=True)
            status = run(command, log_path, prefix, config['version'], log=log)
        return status
    except KeyboardInterrupt:
        log.write('Launch cancelled before Acrobat started.', event='shutdown', ACROBAT_STOP_SIGNAL=2)
        return 130
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        log.write(str(error), priority=3, event='launch-error')
        print(f'Acrobat: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
