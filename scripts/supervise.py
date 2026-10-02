#!/usr/bin/env python3
"""Run Wine with persistent journal diagnostics and bounded fallback logs."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import selectors
import signal
import socket
import struct
import subprocess
import sys
import time
import uuid

IDENTIFIER = 'acrobat-wine'
FATAL = re.compile(r'Unhandled exception|Assertion failed|malloc\(\):|\bFATAL\b|stack overflow', re.I)
GRAPHICS = re.compile(r'lib(?:nvidia|GLX|EGL|vulkan)|wined3d|d3d11|dxgi|swiftshader|swrast|llvmpipe', re.I)
CRASH_IMAGES = re.compile(r'/(?:libcef\.dll|Acrobat\.dll|ntdll\.so|crypt32\.dll|msftedit\.dll|user32\.dll)$', re.I)
ADOBE_IMAGES = {b'acrobat.exe', b'acrocef.exe', b'rdrcef.exe', b'adobecollabsync.exe'}
ADOBE_HELPERS = ADOBE_IMAGES - {b'acrobat.exe'}


def launch_processes(token, number=None, exclude_pid=None, names=ADOBE_IMAGES):
    """Find this launch's Adobe processes, including Wine's detached children.

    Never signal a shared wineserver or another launch in the same prefix.
    A pidfd plus a second identity check prevents signalling a reused PID.
    """
    required = ('ACROBAT_LAUNCH_ID=' + token).encode()
    found = []
    for proc in Path('/proc').glob('[0-9]*'):
        descriptor = None
        try:
            if required not in (proc / 'environ').read_bytes().split(b'\0'):
                continue
            name = (proc / 'cmdline').read_bytes().split(b'\0')[0].replace(b'\\', b'/').split(b'/')[-1].lower()
            if name not in names:
                continue
            pid = int(proc.name)
            if number is not None:
                if pid == exclude_pid:
                    continue
                descriptor = os.pidfd_open(pid)
                if required not in (proc / 'environ').read_bytes().split(b'\0'):
                    continue
                current = (proc / 'cmdline').read_bytes().split(b'\0')[0].replace(b'\\', b'/').split(b'/')[-1].lower()
                if current != name:
                    continue
                signal.pidfd_send_signal(descriptor, number)
            found.append((pid, name))
        except OSError:
            continue
        finally:
            if descriptor is not None:
                os.close(descriptor)
    return found


def signal_group(process, number):
    if process is not None and process.poll() is None:
        try:
            os.killpg(process.pid, number)
        except ProcessLookupError:
            pass


class Log:
    def __init__(self, path, session=None):
        self.session = session or uuid.uuid4().hex[:16]
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.Logger(self.session)
        handler = RotatingFileHandler(path, maxBytes=8 * 1024 * 1024, backupCount=3,
                                      encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        self.logger.addHandler(handler)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        self.journal_failed = False

    def write(self, message, priority=6, event='wine', **fields):
        message = str(message).replace('\x00', '\\0')
        # A bounded journal datagram also handles long exception/debug lines.
        encoded = message.encode('utf-8', errors='replace')
        for start in range(0, max(len(encoded), 1), 24000):
            part = encoded[start:start + 24000].decode('utf-8', errors='replace')
            self.logger.info('[%s] %s: %s', self.session, event, part)
            values = {'SYSLOG_IDENTIFIER': IDENTIFIER, 'PRIORITY': str(priority),
                      'MESSAGE': part, 'ACROBAT_SESSION': self.session,
                      'ACROBAT_EVENT': event, **{k: str(v) for k, v in fields.items()}}
            payload = bytearray()
            for key, value in values.items():
                data = value.encode('utf-8', errors='replace')
                if b'\n' in data:
                    payload += key.encode() + b'\n' + struct.pack('<Q', len(data)) + data + b'\n'
                else:
                    payload += key.encode() + b'=' + data + b'\n'
            try:
                self.socket.sendto(payload, '/run/systemd/journal/socket')
            except OSError as error:
                if not self.journal_failed:
                    self.logger.warning('Journal unavailable (%s); file logging remains active.', error)
                    self.journal_failed = True


def processes(prefix):
    required = ('WINEPREFIX=' + str(prefix)).encode()
    result = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if required not in (proc / 'environ').read_bytes().split(b'\0'):
                continue
            args = (proc / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
            if not args or not any(n in args[0].lower() for n in
                                   [b'acrobat.exe', b'acrocef.exe', b'winedbg', b'adobecollabsync.exe']):
                continue
            arguments = [a.decode(errors='replace') for a in args]
            role = next((a.partition('=')[2] for a in arguments if a.startswith('--type=')), 'main')
            row = {'pid': int(proc.name), 'executable': arguments[0], 'role': role,
                   'gpu_disabled': any(a in arguments for a in
                                       ['--disable-gpu', '--disable-gpu-compositing'])}
            try:
                mappings = (proc / 'maps').read_text().splitlines()
                row['graphics_libraries'] = sorted({line.split(maxsplit=5)[-1] for line in mappings
                                                    if '/' in line and GRAPHICS.search(line)})
                row['crash_image_mappings'] = [line for line in mappings if CRASH_IMAGES.search(line)]
            except OSError as error:
                row['mapping_error'] = str(error)
            result.append(row)
        except (OSError, ValueError):
            continue
    return result


def graphics_info():
    devices = sorted(str(p) for pattern in ['/dev/dri/renderD*', '/dev/nvidia*']
                     for p in Path('/').glob(pattern.lstrip('/')))
    result = {'devices': devices, 'display': os.environ.get('DISPLAY'),
              'wayland_display': os.environ.get('WAYLAND_DISPLAY'),
              'software_forced': os.environ.get('LIBGL_ALWAYS_SOFTWARE', '<unset>'),
              'driver_path': '/run/opengl-driver' if Path('/run/opengl-driver').exists() else None}
    version = Path('/proc/driver/nvidia/version')
    if version.is_file():
        result['nvidia_driver'] = version.read_text().splitlines()[0]
    return result


def run(command, log_path, prefix, version, observer=processes, log=None):
    log = log or Log(log_path)
    log.write(f'Starting Acrobat {version}', event='startup',
              ACROBAT_PREFIX=prefix, ACROBAT_VERSION=version)
    log.write(json.dumps(graphics_info(), sort_keys=True), event='graphics')
    log.write(f'WINEDEBUG={os.environ.get("WINEDEBUG", "<unset>")}; '
              f'WINEDLLOVERRIDES={os.environ.get("WINEDLLOVERRIDES", "<unset>")}', event='runtime')
    started = time.monotonic()
    token = uuid.uuid4().hex
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True,
                                   env={**os.environ, 'ACROBAT_LAUNCH_ID': token})
    except OSError as error:
        log.write(f'Unable to start Wine: {error}', priority=3, event='launch-error')
        return 127
    log.write(f'Wine launcher PID {process.pid}', event='process-start', ACROBAT_PROCESS_ID=process.pid)
    requested_signal = 0
    requests = 0

    def request_stop(number, frame):
        nonlocal requested_signal, requests
        requested_signal = requested_signal or number
        requests += 1

    previous_handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[sig] = signal.signal(sig, request_stop)
    selector = selectors.DefaultSelector()
    os.set_blocking(process.stdout.fileno(), False)
    selector.register(process.stdout, selectors.EVENT_READ)
    pending = b''
    next_snapshot = started + 1
    previous_snapshot = None
    last_repeated = None
    repeated = 0
    observed_fatal = False
    exited_at = None
    closing_at = None
    cleanup_stage = 0
    cleanup_at = None
    shutdown_stage = 0
    shutdown_at = None
    handled_requests = 0

    def send_stop(number):
        signal_group(process, number)
        launch_processes(token, number, exclude_pid=process.pid)
        log.write(f'Sending {signal.Signals(number).name} to this launch.',
                  event='shutdown', ACROBAT_STOP_SIGNAL=requested_signal)

    def emit(line):
        nonlocal observed_fatal, next_snapshot, last_repeated, repeated
        text = line.decode('utf-8', errors='replace').rstrip('\r')
        if not text:
            return
        if text == last_repeated:
            repeated += 1
            return
        if repeated:
            log.write(f'Previous Wine message repeated {repeated} more times.', event='repeated')
            repeated = 0
        last_repeated = text
        fatal = bool(FATAL.search(text))
        priority = 3 if fatal or ':err:' in text else 4 if ':warn:' in text else 6
        log.write(text, priority=priority, event='crash' if fatal else 'wine')
        if fatal:
            observed_fatal = True
            next_snapshot = 0

    try:
        while True:
            now = time.monotonic()
            if requested_signal:
                if shutdown_stage == 0:
                    log.write('Shutdown requested; escalation is limited to this launch.', event='shutdown',
                              ACROBAT_STOP_SIGNAL=requested_signal)
                    if sys.stderr.isatty():
                        print('Acrobat: stopping...', file=sys.stderr, flush=True)
                    send_stop(requested_signal)
                    shutdown_stage = 1 if requested_signal == signal.SIGINT else 2
                    shutdown_at = now + (2 if shutdown_stage == 1 else 1)
                    handled_requests = requests
                elif shutdown_stage < 3 and (now >= shutdown_at or requests > handled_requests):
                    shutdown_stage += 1
                    send_stop(signal.SIGTERM if shutdown_stage == 2 else signal.SIGKILL)
                    shutdown_at = now + (1 if shutdown_stage == 2 else .5)
                    handled_requests = requests
                if process.poll() is not None and not launch_processes(token):
                    break
                if shutdown_stage == 3 and now >= shutdown_at:
                    break
            if now >= next_snapshot:
                snapshot = observer(prefix)
                if snapshot != previous_snapshot:
                    log.write(json.dumps(snapshot, sort_keys=True), event='processes')
                    previous_snapshot = snapshot
                next_snapshot = now + 5
            for key, _ in selector.select(0.2):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    emit(line)
                if len(pending) > 24000:
                    emit(pending[:24000])
                    pending = pending[24000:]
            if process.poll() is not None:
                if exited_at is None:
                    exited_at = now
                    log.write(f'Wine launcher exited: status={process.returncode}', event='process-exit',
                              ACROBAT_CHILD_STATUS=process.returncode)
                if not requested_signal:
                    owned = launch_processes(token)
                    # Acrobat can restart into a detached process. Keep its
                    # picker and AppImage mount while that GUI is still alive.
                    if any(name == b'acrobat.exe' for _, name in owned):
                        closing_at = None
                        cleanup_stage = 0
                        continue
                    closing_at = closing_at or now
                    # Allow a short process handoff and drain final log output.
                    # EOF and a shared wineserver are not application lifetimes.
                    if now - closing_at < .25:
                        continue
                    if not owned:
                        break
                    if cleanup_stage == 0:
                        log.write('Acrobat exited; stopping its remaining Adobe helpers with SIGTERM.',
                                  event='shutdown')
                        launch_processes(token, signal.SIGTERM, names=ADOBE_HELPERS)
                        cleanup_stage = 1
                        cleanup_at = now + 1
                    elif now >= cleanup_at:
                        if cleanup_stage == 1:
                            log.write('Adobe helpers did not stop; sending SIGKILL to those from this launch.',
                                      event='shutdown')
                            launch_processes(token, signal.SIGKILL, names=ADOBE_HELPERS)
                            cleanup_stage = 2
                            cleanup_at = now + .5
                        else:
                            log.write('Ending the bounded Adobe helper cleanup.', priority=4, event='shutdown')
                            break
        if pending:
            emit(pending)
        if repeated:
            log.write(f'Previous Wine message repeated {repeated} more times.', event='repeated')
    finally:
        selector.close()
        process.stdout.close()
        for sig, previous in previous_handlers.items():
            signal.signal(sig, previous)
    status = process.poll()
    result = 128 + requested_signal if requested_signal else status
    log.write(f'Acrobat exited: status={status}; elapsed={time.monotonic() - started:.1f}s; '
              f'fatal_message_observed={observed_fatal}; stop_signal={requested_signal}. '
              'Status 1 alone is not proof of a crash.',
              priority=3 if observed_fatal or (status is not None and status < 0 and not requested_signal) else 6,
              event='exit', ACROBAT_EXIT_STATUS=result, ACROBAT_CHILD_STATUS=status,
              ACROBAT_STOP_SIGNAL=requested_signal)
    return result if result >= 0 else 128 - result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', required=True)
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--version', default='26.002.21931')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('A command is required after --.')
    raise SystemExit(run(command, args.log, args.prefix, args.version))
