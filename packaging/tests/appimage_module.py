"""Exercise the built NixOS launcher without starting the private application."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

COMMANDS = json.loads(Path(sys.argv.pop(1)).read_text())
ENVIRONMENT = {key: value for key, value in os.environ.items()
               if key not in {'DBUS_SESSION_BUS_ADDRESS', 'DISPLAY', 'WAYLAND_DISPLAY'}}


class AppImageModuleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name) / 'cache'
        self.environment = dict(ENVIRONMENT, XDG_CACHE_HOME=str(self.cache))

    def run_command(self, name, *arguments):
        return subprocess.run([COMMANDS[name], *arguments], env=self.environment,
                              capture_output=True, timeout=15)

    def test_arguments_and_image_path_preserve_spaces_unicode_and_shell_characters(self):
        arguments = ['--', 'report é 100%.pdf', "a file's name.pdf", '$(not-a-command)', '*.pdf']
        result = self.run_command('good', *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b'\0'.join(arg.encode() for arg in arguments) + b'\0')

    def test_optional_checksum(self):
        result = self.run_command('unpinned', 'document.pdf')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b'document.pdf\0')
        self.assertFalse(self.cache.exists())

    def test_verification_cache_is_reused_by_the_installed_launcher(self):
        self.assertEqual(self.run_command('good', 'first.pdf').returncode, 0)
        entry, = self.cache.glob('acrobat-wine/verified-appimages/*.json')
        before = entry.stat()
        self.assertEqual(self.run_command('good', 'second.pdf').stdout, b'second.pdf\0')
        self.assertEqual(entry.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertIn('sha256', json.loads(entry.read_text()))

    def test_every_launch_verification_can_be_requested(self):
        self.assertEqual(self.run_command('uncached', 'first.pdf').returncode, 0)
        self.assertEqual(self.run_command('uncached', 'second.pdf').stdout, b'second.pdf\0')
        self.assertFalse(self.cache.exists())

    def test_normal_application_exit_status_is_preserved(self):
        for status in (0, 1, 130):
            with self.subTest(status=status):
                result = self.run_command('good', '--exit', str(status))
                self.assertEqual(result.returncode, status, result.stderr)

    def test_missing_download_explains_where_to_put_it(self):
        result = self.run_command('missing', 'document.pdf')
        self.assertEqual(result.returncode, 127)
        self.assertIn(b'Download the private AppImage to:', result.stderr)
        self.assertEqual(result.stdout, b'')

    def test_download_without_executable_permission_has_actionable_error(self):
        result = self.run_command('notExecutable')
        self.assertEqual(result.returncode, 126)
        self.assertIn(b'chmod +x', result.stderr)

    def test_checksum_mismatch_prevents_execution(self):
        result = self.run_command('wrongHash', 'document.pdf')
        self.assertEqual(result.returncode, 1)
        self.assertIn(b'checksum does not match', result.stderr)
        self.assertEqual(result.stdout, b'')

    def test_exec_preserves_pid_and_terminal_signal_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'pid'
            environment = dict(self.environment, ACROBAT_TEST_PIDFILE=str(pidfile))
            process = subprocess.Popen([COMMANDS['good'], '--wait'], env=environment,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 10
                while not pidfile.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(pidfile.exists(), 'Fixture never started')
                self.assertEqual(int(pidfile.read_text()), process.pid)
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=3), -signal.SIGTERM)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stderr.close()

    def test_desktop_entry_opens_pdfs_with_the_launcher(self):
        desktop = Path(COMMANDS['desktop']).read_text()
        self.assertIn('Name=Acrobat (Wine)\n', desktop)
        executable = next(line.removeprefix('Exec=') for line in desktop.splitlines()
                          if line.startswith('Exec='))
        self.assertTrue(executable.endswith(' %F'))
        self.assertEqual(Path(executable.removesuffix(' %F')).resolve(),
                         Path(COMMANDS['good']).resolve())
        self.assertIn('MimeType=application/pdf', desktop)
        self.assertIn('StartupWMClass=acrobat.exe\n', desktop)
        self.assertIn('Terminal=false\n', desktop)


if __name__ == '__main__':
    unittest.main(verbosity=2)
