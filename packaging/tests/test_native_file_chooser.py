import asyncio
import fnmatch
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dbus_next import Message, MessageType, Variant
from dbus_next.aio import MessageBus

import native_file_chooser as picker


def request_bytes(*, options=0x1208, filters=None, folder='', title='Open'):
    filters = filters if filters is not None else [('Adobe PDF Files (*.pdf)', '*.pdf'), ('All files', '*.*')]
    data = bytearray(struct.pack('<5I', picker.MAGIC, options, 0, len(filters), 0x12345))
    for value in [title, '', folder, ''] + [v for pair in filters for v in pair]:
        encoded = value.encode('utf-16-le')
        data += struct.pack('<I', len(encoded) // 2) + encoded
    return bytes(data)


def response_values(data):
    magic, status, index, count = struct.unpack_from('<4I', data)
    assert magic == picker.MAGIC
    offset, paths = 16, []
    for _ in range(count):
        length, = struct.unpack_from('<I', data, offset)
        offset += 4
        paths.append(data[offset:offset + length * 2].decode('utf-16-le'))
        offset += length * 2
    assert offset == len(data)
    return status, index, paths


class PathsAndFilters(unittest.TestCase):
    def test_windows_filters_keep_case_insensitivity_and_all_files(self):
        filters = picker.portal_filters([('PDF', '*.pdf; *.xps'), ('All', '*.*')])
        self.assertTrue(fnmatch.fnmatchcase('REPORT.PdF', filters[0][1][0][1]))
        self.assertFalse(fnmatch.fnmatchcase('report.txt', filters[0][1][0][1]))
        self.assertTrue(fnmatch.fnmatchcase('README', filters[1][1][0][1]))
        self.assertTrue(fnmatch.fnmatchcase('file[1].PDF', picker.windows_glob('file[1].pdf')))

    def test_truncated_and_oversized_messages_are_rejected(self):
        valid = request_bytes()
        for data in (valid[:19], valid[:-1], valid + b'extra', b'X' * (picker.MAX_BYTES + 1)):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                picker.decode_request(data)

    def test_uri_validation_does_not_accept_remote_or_missing_files(self):
        request = picker.decode_request(request_bytes())
        for uri in ('https://example.com/a.pdf', 'file://remote/a.pdf', 'file:///nonexistent/acrobat-test',
                    'file:///tmp/a%00.pdf', 'file:relative.pdf'):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                picker.selected_paths([uri], request)


class PortalIntegration(unittest.IsolatedAsyncioTestCase):
    """Exercise the actual D-Bus and file protocol on an isolated session bus."""
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        # Nix checks have no host /etc/dbus-1/session.conf. This bus needs only
        # the test's two peers, with no desktop services or activation paths.
        config = self.root / 'bus.conf'
        config.write_text('''<busconfig><type>session</type>
            <listen>unix:tmpdir=/tmp</listen><auth>EXTERNAL</auth>
            <policy context="default"><allow own="*"/><allow send_destination="*"/>
            <allow receive_sender="*"/></policy></busconfig>''')
        self.daemon = subprocess.Popen(['dbus-daemon', '--config-file=' + str(config),
                                       '--nofork', '--print-address=1'],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.address = self.daemon.stdout.readline().strip()
        if not self.address:
            raise RuntimeError('Private test bus failed: ' + self.daemon.stderr.read())
        self.environment = patch.dict(os.environ, {'DBUS_SESSION_BUS_ADDRESS': self.address})
        self.environment.start()
        self.backend = await MessageBus().connect()
        await self.backend.request_name(picker.PORTAL)
        self.backend.add_message_handler(self.handle)
        self.calls, self.closed = [], []
        self.mode = 'success'
        self.changed_handle = False
        self.documents = [self.root / 'report é 100%.PDF', self.root / 'second document.pdf']
        for document in self.documents:
            document.write_bytes(b'%PDF-1.7 test document')
        self.prefix = self.root / 'prefix'
        (self.prefix / 'dosdevices').mkdir(parents=True)
        (self.prefix / 'dosdevices/h:').symlink_to(self.root)
        self.client = picker.Portal(self.prefix)
        await self.client.connect()

    async def asyncTearDown(self):
        await self.client.disconnect()
        await picker.close_bus(self.backend)
        self.environment.stop()
        self.daemon.terminate()
        self.daemon.wait(timeout=3)
        self.daemon.stdout.close()
        self.daemon.stderr.close()
        self.temporary.cleanup()

    def handle(self, message):
        if message.message_type != MessageType.METHOD_CALL:
            return
        if message.interface == 'org.freedesktop.DBus.Properties' and message.member == 'Get':
            return Message.new_method_return(message, 'v', [Variant('u', 4)])
        if message.interface == picker.REQUEST and message.member == 'Close':
            self.closed.append(message.path)
            return Message.new_method_return(message)
        if message.interface != picker.FILE_CHOOSER or message.member != 'OpenFile':
            return
        self.calls.append(message.body)
        if self.mode == 'error':
            return Message.new_error(message, 'org.freedesktop.portal.Error.Failed', 'Backend unavailable')
        token = message.body[2]['handle_token'].value
        if self.changed_handle:
            token += '_different'
        handle = f'{picker.PORTAL_PATH}/request/{message.sender[1:].replace(".", "_")}/{token}'
        if self.mode != 'pending':
            code = 1 if self.mode == 'cancel' else 0
            # Signal deliberately precedes the method reply: don't lose fast selections.
            self.backend.send(Message.new_signal(handle, picker.REQUEST, 'Response', 'ua{sv}', [code, {
                'uris': Variant('as', [p.as_uri() for p in self.documents]),
                'current_filter': Variant('(sa(us))', ['All files', [[0, '*']]]),
            }]))
        return Message.new_method_return(message, 'o', [handle])

    async def test_selection_uses_parent_filters_folder_and_preserves_unicode(self):
        result = await self.client.choose(picker.decode_request(request_bytes(folder='H:\\')), 'selection')
        status, index, paths = response_values(result)
        self.assertEqual((status, index), (0, 1))
        self.assertEqual(paths, ['Z:' + str(p).replace('/', '\\') for p in self.documents])
        parent, title, options = self.calls[0]
        self.assertEqual((parent, title), ('x11:12345', 'Open'))
        self.assertTrue(options['multiple'].value)
        self.assertEqual(options['current_folder'].value, os.fsencode(self.root) + b'\0')
        self.assertEqual(options['current_filter'].value[0], 'Adobe PDF Files (*.pdf)')

    async def test_response_before_changed_handle_reply_is_retained(self):
        self.changed_handle = True
        result = await self.client.choose(picker.decode_request(request_bytes()), 'changed')
        self.assertEqual(response_values(result)[0], 0)

    async def test_cancel_returns_no_selected_files(self):
        self.mode = 'cancel'
        result = await self.client.choose(picker.decode_request(request_bytes()), 'cancel')
        self.assertEqual(response_values(result), (1, 0, []))

    async def test_cancelled_windows_request_closes_native_dialog(self):
        self.mode = 'pending'
        task = asyncio.create_task(self.client.choose(picker.decode_request(request_bytes()), 'pending'))
        for _ in range(100):
            if self.calls:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(self.calls)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.closed), 1)

    async def test_broker_returns_fallback_and_cleans_private_directory(self):
        self.mode = 'error'
        messages = []
        class Log:
            def write(self, message, **unused): messages.append(message)
        bridge = picker.NativeFileChooser(self.root / 'run', self.prefix, Log())
        await asyncio.to_thread(bridge.__enter__)
        try:
            self.assertTrue((bridge.directory / 'ready').exists())
            self.assertEqual(bridge.directory.stat().st_mode & 0o777, 0o700)
            self.assertIn('ACROBAT_FILE_CHOOSER_DIR', os.environ)
            request = bridge.directory / '00000020-00000024-00000001.req'
            request.write_bytes(request_bytes())
            reply = request.with_suffix('.res')
            for _ in range(200):
                if reply.exists():
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(response_values(reply.read_bytes()), (2, 0, []))
            self.assertTrue(any('falling back' in message for message in messages))
        finally:
            await asyncio.to_thread(bridge.__exit__)
        self.assertFalse(bridge.directory.exists())
        self.assertNotIn('ACROBAT_FILE_CHOOSER_DIR', os.environ)


if __name__ == '__main__':
    unittest.main()
