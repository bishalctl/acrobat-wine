"""Return desktop-portal selections to the bundled Wine IFileOpenDialog.

Wine and the Linux broker exchange bounded, length-prefixed UTF-16 messages in
a private per-launch directory. Requests stay present until Wine consumes the
answer; removing one cancels its portal dialog. A heartbeat lets Wine fall back
if this process or its D-Bus connection disappears.
"""
import asyncio
from contextlib import suppress
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import tempfile
import threading
from urllib.parse import unquote, urlsplit

MAGIC = 0x31505741  # AWP1, little endian
MAX_BYTES = 1024 * 1024
MAX_STRING = 32767
MAX_FILES = 1024
FOS_PICKFOLDERS = 0x20
FOS_ALLOWMULTISELECT = 0x200
PORTAL = 'org.freedesktop.portal.Desktop'
PORTAL_PATH = '/org/freedesktop/portal/desktop'
FILE_CHOOSER = 'org.freedesktop.portal.FileChooser'
REQUEST = 'org.freedesktop.portal.Request'
REQUEST_NAME = re.compile(r'[0-9a-f]{8}-[0-9a-f]{8}-[0-9a-f]{8}\.req\Z')


async def close_bus(bus):
    if bus is None:
        return
    bus.disconnect()
    with suppress(Exception):
        await asyncio.wait_for(bus.wait_for_disconnect(), 2)
    # dbus-next 0.2.3 shuts the socket down but leaves both file objects open.
    # Close them after its asyncio readers have been removed.
    bus._stream.close()
    bus._sock.close()


@dataclass
class OpenRequest:
    options: int
    filter_index: int
    xwindow: int
    title: str
    accept_label: str
    folder: str
    filename: str
    filters: list


def decode_request(data):
    if len(data) > MAX_BYTES or len(data) < 20:
        raise ValueError('Invalid file-picker request size')
    magic, options, index, count, xwindow = struct.unpack_from('<5I', data)
    if magic != MAGIC or count > 128 or (count and index >= count):
        raise ValueError('Invalid file-picker request header')
    offset = 20

    def string():
        nonlocal offset
        if offset + 4 > len(data):
            raise ValueError('Truncated file-picker string')
        size, = struct.unpack_from('<I', data, offset)
        offset += 4
        if size > MAX_STRING or offset + size * 2 > len(data):
            raise ValueError('Invalid file-picker string size')
        value = data[offset:offset + size * 2].decode('utf-16-le')
        offset += size * 2
        if '\0' in value:
            raise ValueError('NUL in file-picker string')
        return value

    title, label, folder, filename = [string() for _ in range(4)]
    filters = [(string(), string()) for _ in range(count)]
    if offset != len(data):
        raise ValueError('Trailing file-picker request data')
    return OpenRequest(options, index, xwindow, title, label, folder, filename, filters)


def encode_response(status, index=0, paths=()):
    if status not in (0, 1, 2) or len(paths) > MAX_FILES or (status != 0 and paths):
        raise ValueError('Invalid file-picker response')
    data = bytearray(struct.pack('<4I', MAGIC, status, index, len(paths)))
    for path in paths:
        encoded = path.encode('utf-16-le')
        if '\0' in path or len(encoded) // 2 > MAX_STRING:
            raise ValueError('Invalid selected path')
        data.extend(struct.pack('<I', len(encoded) // 2))
        data.extend(encoded)
    if len(data) > MAX_BYTES:
        raise ValueError('File-picker response is too large')
    return bytes(data)


def windows_glob(pattern):
    """Portal globs are case sensitive; Windows file filters are not."""
    if pattern == '*.*':
        return '*'
    result = []
    for char in pattern:
        if char == '[':
            result.append('[[]')
        elif char == ']':
            result.append('[]]')
        elif char.isalpha() and len(char.lower()) == len(char.upper()) == 1 and char.lower() != char.upper():
            result.append(f'[{char.lower()}{char.upper()}]')
        else:
            result.append(char)
    return ''.join(result)


def portal_filters(filters):
    return [[name, [[0, windows_glob(p.strip())] for p in spec.split(';') if p.strip()]]
            for name, spec in filters]


def unix_folder(value, prefix):
    if not re.match(r'^[A-Za-z]:[\\/]', value):
        return None
    drive = prefix / 'dosdevices' / value[:2].lower()
    path = (drive / value[3:].replace('\\', '/')).resolve()
    return path if path.is_dir() else None


def selected_paths(uris, request):
    if not 1 <= len(uris) <= MAX_FILES:
        raise ValueError('Invalid number of selected files')
    if not request.options & FOS_ALLOWMULTISELECT and len(uris) != 1:
        raise ValueError('Multiple files returned for a single-file dialog')
    paths = []
    for uri in uris:
        parsed = urlsplit(uri)
        if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost') or parsed.query or parsed.fragment:
            raise ValueError('The file picker returned a non-local URI')
        value = unquote(parsed.path, errors='strict')
        if not value.startswith('/') or '\0' in value or '\\' in value:
            raise ValueError('The selected path cannot be represented in Wine')
        path = Path(value)
        if not (path.is_dir() if request.options & FOS_PICKFOLDERS else path.is_file()):
            raise ValueError('The selected file or folder is no longer accessible')
        paths.append('Z:' + value.replace('/', '\\'))
    return paths


class Portal:
    """One D-Bus connection; signal subscription precedes every OpenFile call."""
    def __init__(self, prefix):
        self.prefix = prefix
        self.bus = None
        self.responses = {}
        self.early = {}

    async def connect(self):
        from dbus_next import Message, MessageType, Variant
        from dbus_next.aio import MessageBus
        self.Message, self.MessageType, self.Variant = Message, MessageType, Variant
        self.bus = await asyncio.wait_for(MessageBus().connect(), 3)
        reply = await self.call(Message(destination=PORTAL, path=PORTAL_PATH,
            interface='org.freedesktop.DBus.Properties', member='Get',
            signature='ss', body=[FILE_CHOOSER, 'version']))
        if reply.body[0].value < 3:
            raise RuntimeError('The desktop file-picker portal is too old')
        self.sender = self.bus.unique_name[1:].replace('.', '_')
        self.bus.add_message_handler(self.on_message)
        await self.call(Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
            interface='org.freedesktop.DBus', member='AddMatch', signature='s', body=[
                "type='signal',sender='org.freedesktop.portal.Desktop',"
                "interface='org.freedesktop.portal.Request',member='Response',"
                f"path_namespace='{PORTAL_PATH}/request/{self.sender}'"]))

    async def call(self, message):
        reply = await asyncio.wait_for(self.bus.call(message), 5)
        if reply.message_type == self.MessageType.ERROR:
            raise RuntimeError(f'File-picker portal: {reply.error_name}')
        return reply

    def on_message(self, message):
        if (message.message_type != self.MessageType.SIGNAL or message.interface != REQUEST
                or message.member != 'Response'
                or not message.path.startswith(f'{PORTAL_PATH}/request/{self.sender}/')):
            return
        future = self.responses.get(message.path)
        if future is not None:
            if not future.done():
                future.set_result(message.body)
        elif len(self.early) < 128:
            self.early[message.path] = message.body

    async def choose(self, request, token):
        Variant, Message = self.Variant, self.Message
        options = {'handle_token': Variant('s', token), 'modal': Variant('b', True),
            'multiple': Variant('b', bool(request.options & FOS_ALLOWMULTISELECT)),
            'directory': Variant('b', bool(request.options & FOS_PICKFOLDERS))}
        if request.accept_label:
            options['accept_label'] = Variant('s', request.accept_label.replace('&', ''))
        filters = portal_filters(request.filters)
        if filters and not request.options & FOS_PICKFOLDERS:
            options['filters'] = Variant('a(sa(us))', filters)
            options['current_filter'] = Variant('(sa(us))', filters[request.filter_index])
        folder = unix_folder(request.folder, self.prefix)
        if folder:
            options['current_folder'] = Variant('ay', os.fsencode(folder) + b'\0')
        parent = f'x11:{request.xwindow:x}' if request.xwindow else ''
        handle = f'{PORTAL_PATH}/request/{self.sender}/{token}'
        future = asyncio.get_running_loop().create_future()
        self.responses[handle] = future
        completed = False
        try:
            reply = await self.call(Message(destination=PORTAL, path=PORTAL_PATH,
                interface=FILE_CHOOSER, member='OpenFile', signature='ssa{sv}',
                body=[parent, request.title or 'Open', options]))
            actual = reply.body[0]
            if actual != handle:
                self.responses.pop(handle, None)
                handle = actual
                self.responses[handle] = future
                if handle in self.early and not future.done():
                    future.set_result(self.early.pop(handle))
            code, results = await future
            completed = True
            if code == 1:
                return encode_response(1)
            if code != 0:
                return encode_response(2)
            index = request.filter_index
            if 'current_filter' in results and results['current_filter'].value in filters:
                index = filters.index(results['current_filter'].value)
            return encode_response(0, index, selected_paths(results['uris'].value, request))
        finally:
            self.responses.pop(handle, None)
            self.early.pop(handle, None)
            if not completed:
                with suppress(Exception):
                    await self.call(Message(destination=PORTAL, path=handle, interface=REQUEST, member='Close'))

    async def disconnect(self):
        await close_bus(self.bus)


class NativeFileChooser:
    def __init__(self, state, prefix, log):
        self.state, self.prefix, self.log = state, prefix, log
        self.directory = None
        self.stop = threading.Event()
        self.started = threading.Event()
        self.thread = None

    def __enter__(self):
        self.previous = os.environ.pop('ACROBAT_FILE_CHOOSER_DIR', None)
        if os.environ.get('ACROBAT_NATIVE_FILE_CHOOSER', '1') == '0':
            return self
        if not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
            self.log.write('No desktop session bus; using Wine file dialogs.', event='file-chooser')
            return self
        self.state.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix='file-chooser-', dir=self.state))
        self.thread = threading.Thread(target=self.serve, name='native-file-chooser', daemon=True)
        self.thread.start()
        self.started.wait(4)
        if (self.directory / 'ready').exists():
            os.environ['ACROBAT_FILE_CHOOSER_DIR'] = 'Z:' + str(self.directory).replace('/', '\\')
            self.log.write('Desktop portal enabled for Open dialogs.', event='file-chooser')
        else:
            self.stop.set()
        return self

    def __exit__(self, *unused):
        os.environ.pop('ACROBAT_FILE_CHOOSER_DIR', None)
        if self.previous is not None:
            os.environ['ACROBAT_FILE_CHOOSER_DIR'] = self.previous
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=7)
        if self.directory and (not self.thread or not self.thread.is_alive()):
            shutil.rmtree(self.directory, ignore_errors=True)

    def serve(self):
        try:
            asyncio.run(self.run())
        except Exception as error:
            self.log.write(f'Native picker unavailable ({error}); using Wine dialogs.', event='file-chooser')
        finally:
            (self.directory / 'ready').unlink(missing_ok=True)
            self.started.set()

    async def answer(self, path, portal):
        try:
            with path.open('rb') as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise ValueError('Invalid file-picker request file')
                request = decode_request(source.read(MAX_BYTES + 1))
            response = await portal.choose(request, 'acrobat_' + path.stem.replace('-', '_'))
            status, index, count = struct.unpack_from('<3I', response, 4)
            self.log.write({0: f'Selected {count} file(s).', 1: 'Selection cancelled.',
                2: 'Desktop picker unavailable; falling back to Wine.'}[status], event='file-chooser')
        except Exception as error:
            self.log.write(f'Native picker failed ({error}); falling back to Wine.', event='file-chooser')
            response = encode_response(2)
        if path.exists():
            temporary = path.with_suffix('.reply')
            temporary.write_bytes(response)
            temporary.replace(path.with_suffix('.res'))

    async def run(self):
        portal = Portal(self.prefix)
        tasks = {}
        disconnected = None
        try:
            await portal.connect()
            disconnected = asyncio.create_task(portal.bus.wait_for_disconnect())
            (self.directory / 'ready').touch(mode=0o600)
            self.started.set()
            while not self.stop.is_set() and not disconnected.done():
                (self.directory / 'ready').touch()
                for path in self.directory.glob('*.req'):
                    if REQUEST_NAME.fullmatch(path.name) and not path.is_symlink() and path not in tasks:
                        tasks[path] = asyncio.create_task(self.answer(path, portal))
                for path, task in list(tasks.items()):
                    if not path.exists():
                        if not task.done():
                            task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        path.with_suffix('.res').unlink(missing_ok=True)
                        tasks.pop(path)
                await asyncio.sleep(0.1)
        finally:
            (self.directory / 'ready').unlink(missing_ok=True)
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            await portal.disconnect()
            if disconnected:
                await asyncio.gather(disconnected, return_exceptions=True)
