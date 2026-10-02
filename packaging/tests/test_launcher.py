import importlib.util
import json
import os
from pathlib import Path
import pwd
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

import host_files
import launcher
import supervise

export_spec = importlib.util.spec_from_file_location('export_profile',
    Path(__file__).resolve().parent.parent / 'export-profile.py')
# Flake checks put their source files together in a temporary directory.
if not Path(export_spec.origin).exists():
    export_spec = importlib.util.spec_from_file_location('export_profile',
        Path(__file__).resolve().parent / 'export-profile.py')
export_profile = importlib.util.module_from_spec(export_spec)
export_spec.loader.exec_module(export_profile)


class Export(unittest.TestCase):
    def test_host_font_caches_and_previous_sessions_are_not_portable(self):
        original = (r'''WINE REGISTRY Version 2

[Software\\Adobe\\Adobe Acrobat\\DC\\SessionManagement\\cWindowsPrev]
"filename"="private.pdf"

[Software\\Wine\\Fonts\\External Fonts]
"Arial"="Z:\\old-checkout\\arial.ttf"

[Software\\Microsoft\\Windows NT\\CurrentVersion\\Fonts]
"Old host font"="Z:\\old-machine\\font.ttf"
"Selawik"="selawk.ttf"

[Software\\Adobe\\Adobe Acrobat\\DC\\CEF]
"bDisableGPU"=dword:00000000
''').encode()
        cleaned = export_profile.clean_registry(original).decode()
        self.assertNotIn('old-checkout', cleaned)
        self.assertNotIn('old-machine', cleaned)
        self.assertNotIn('private.pdf', cleaned)
        self.assertIn('"Selawik"="selawk.ttf"', cleaned)
        self.assertIn('"bDisableGPU"=dword:00000000', cleaned)


class HostFiles(unittest.TestCase):
    def test_root_and_home_follow_user_permissions_and_preserve_documents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / 'home'
            home.mkdir(mode=0o750)
            prefix = root / 'prefix'
            documents = prefix / 'drive_c/users' / pwd.getpwuid(os.getuid()).pw_name / 'Documents'
            documents.mkdir(parents=True)
            (documents / 'keep.pdf').write_bytes(b'original user data')
            mode = home.stat().st_mode
            host_files.configure(prefix, home)
            self.assertEqual(os.readlink(prefix / 'dosdevices/z:'), '/')
            self.assertEqual((prefix / 'dosdevices/h:').resolve(), home)
            self.assertEqual((documents / 'keep.pdf').read_bytes(), b'original user data')
            self.assertEqual(home.stat().st_mode, mode)
            # A mapping exposes a genuinely external file without copying it.
            outside = root / 'outside.pdf'
            outside.write_bytes(b'outside the prefix')
            through_z = prefix / 'dosdevices/z:' / str(outside).lstrip('/')
            self.assertEqual(through_z.read_bytes(), b'outside the prefix')

    def test_real_drive_directory_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary)
            (prefix / 'dosdevices/z:').mkdir(parents=True)
            (prefix / 'dosdevices/z:/keep').write_text('data')
            with self.assertRaises(RuntimeError):
                host_files.configure(prefix)
            self.assertEqual((prefix / 'dosdevices/z:/keep').read_text(), 'data')


class Arguments(unittest.TestCase):
    def test_file_uri_with_unicode_spaces_and_literal_percent(self):
        with tempfile.TemporaryDirectory() as temporary:
            document = Path(temporary) / 'report \u00e9 100%.pdf'
            document.touch()
            expected = 'Z:' + str(document).replace('/', '\\')
            self.assertEqual(launcher.windows_argument(document.as_uri()), expected)
            self.assertEqual(launcher.windows_argument(str(document)), expected)

    def test_remote_file_uri_is_not_treated_as_local(self):
        with self.assertRaises(ValueError):
            launcher.windows_argument('file://remote-server/private.pdf')


class Initialization(unittest.TestCase):
    def test_corrupt_archive_does_not_create_or_replace_a_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'archive'
            archive.write_bytes(b'corrupt')
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'archive_sha256': '0' * 64}))
            config = {'version': '26.002.21931', 'archive': str(archive), 'manifest': str(manifest)}
            class QuietLog:
                def write(self, *args, **kwargs): pass
            with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
                launcher.initialize(config, root / 'data', QuietLog())
            self.assertFalse((root / 'data/prefix').exists())

    def test_user_paths_and_visible_root_shortcuts_are_rebased(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary)
            (prefix / 'drive_c/users/exporter').mkdir(parents=True)
            for name in ['user.reg', 'userdef.reg', 'system.reg']:
                (prefix / name).write_text('WINE REGISTRY Version 2\n\n[Example]\n"path"="C:\\\\users\\\\exporter\\\\Documents"\n')
            with patch.object(launcher, 'configure_host_files'):
                launcher.personalize(prefix, 'exporter')
            text = (prefix / 'user.reg').read_text()
            username = pwd.getpwuid(os.getuid()).pw_name
            self.assertIn('C:\\\\users\\\\' + username, text)
            self.assertNotIn('exporter', text)
            self.assertIn('Linux filesystem (/)', text)
            self.assertIn('"tDIText"="/H/"', text)
            self.assertIn('"tDIText"="/Z/"', text)


class DesktopLaunch(unittest.TestCase):
    def test_hyprland_session_launches_without_compositor_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / 'data'
            prefix = data / 'prefix'
            executable = prefix / 'drive_c/Program Files/Adobe/Acrobat DC/Acrobat/Acrobat.exe'
            executable.parent.mkdir(parents=True)
            executable.touch()
            (data / 'profile.json').write_text(json.dumps({
                'schema': 1, 'application_version': '26.002.21931',
            }))
            captured = root / 'wine-call.json'
            wine = root / 'wine'
            wine.write_text(
                f'#!{sys.executable}\n'
                'import json, os, sys\n'
                'from pathlib import Path\n'
                'if sys.argv[1:] != ["-w"]:\n'
                f'    Path({str(captured)!r}).write_text(json.dumps({{'
                '"arguments": sys.argv[1:], "prefix": os.environ["WINEPREFIX"]}))\n'
            )
            wine.chmod(0o700)
            (root / 'runtime.json').write_text(json.dumps({
                'version': '26.002.21931', 'wine': str(wine), 'wineserver': str(wine),
            }))
            empty_bin = root / 'empty-bin'
            empty_bin.mkdir()
            environment = {
                'ACROBAT_DATA_HOME': str(data), 'ACROBAT_STATE_HOME': str(root / 'state'),
                'HYPRLAND_INSTANCE_SIGNATURE': 'test-compositor', 'PATH': str(empty_bin),
            }

            class QuietLog:
                def __init__(self, *args, **kwargs): pass
                def write(self, *args, **kwargs): pass

            with patch.dict(os.environ, environment), patch.object(launcher, 'HERE', root), \
                    patch.object(launcher, 'Log', QuietLog), \
                    patch.object(sys, 'argv', ['acrobat-wine']):
                self.assertEqual(launcher.main(), 0)
            call = json.loads(captured.read_text())
            self.assertEqual(call['arguments'], [str(executable)])
            self.assertEqual(call['prefix'], str(prefix))


class Journal(unittest.TestCase):
    def test_multiline_journal_entry_uses_native_binary_encoding(self):
        class Socket:
            messages = []
            def setblocking(self, value): pass
            def sendto(self, payload, destination): self.messages.append(bytes(payload))
        fake = Socket()
        with tempfile.TemporaryDirectory() as temporary, patch.object(supervise.socket, 'socket', return_value=fake):
            log = supervise.Log(Path(temporary) / 'run.log', session='test-session')
            log.write('first line\nsecond line', priority=3, event='crash')
            payload = fake.messages[-1]
            message = b'first line\nsecond line'
            self.assertIn(b'MESSAGE\n' + struct.pack('<Q', len(message)) + message + b'\n', payload)
            self.assertIn(b'SYSLOG_IDENTIFIER=acrobat-wine\n', payload)
            self.assertIn(b'ACROBAT_EVENT=crash\n', payload)
            for handler in log.logger.handlers: handler.close()

    def test_exit_one_alone_does_not_claim_a_crash(self):
        messages = []
        class Capture:
            def __init__(self, *args, **kwargs): pass
            def write(self, message, **fields): messages.append((message, fields))
        with patch.object(supervise, 'Log', Capture):
            status = supervise.run([sys.executable, '-c', 'print("normal close"); raise SystemExit(1)'],
                                   '/unused', '/unused', 'test', observer=lambda prefix: [])
        self.assertEqual(status, 1)
        event = next(fields for message, fields in messages if fields.get('event') == 'exit')
        self.assertEqual(event['priority'], 6)
        self.assertFalse(any(fields.get('event') == 'crash' for _, fields in messages))

    def test_unhandled_exception_is_recorded_as_crash_with_exit_metadata(self):
        messages = []
        class Capture:
            def __init__(self, *args, **kwargs): pass
            def write(self, message, **fields): messages.append((message, fields))
        with patch.object(supervise, 'Log', Capture):
            status = supervise.run([sys.executable, '-c', 'print("wine: Unhandled exception 0x80000003"); raise SystemExit(1)'],
                                   '/unused', '/unused', 'test', observer=lambda prefix: [])
        self.assertEqual(status, 1)
        self.assertTrue(any(fields.get('event') == 'crash' and fields['priority'] == 3 for _, fields in messages))
        event = next(fields for _, fields in messages if fields.get('event') == 'exit')
        self.assertEqual(event['priority'], 3)


if __name__ == '__main__':
    unittest.main()
