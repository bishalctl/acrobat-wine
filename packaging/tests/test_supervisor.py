"""Exercise shutdown with real processes and signals, without starting Wine."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

import supervise


class Shutdown(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.processes = []

    def tearDown(self):
        for process in reversed(self.processes):
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
        self.temporary.cleanup()

    def wait_for(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.025)
        self.fail('Process did not reach the expected state before the deadline')

    def child(self, name, *, ignore_term=True, image=None):
        ready = self.root / (name + '.ready')
        code = (
            'import os, signal, time\n'
            'from pathlib import Path\n'
            'signal.signal(signal.SIGINT, signal.SIG_IGN)\n'
            + ('signal.signal(signal.SIGTERM, signal.SIG_IGN)\n' if ignore_term else '')
            + f'Path({str(ready)!r}).write_text(str(os.getpid()))\n'
            'time.sleep(120)\n'
        )
        command = [image or sys.executable, '-c', code]
        return command, ready

    def launch(self, command):
        log = self.root / 'run.log'
        code = (
            'import sys\n'
            f'sys.path.insert(0, {str(Path(supervise.__file__).parent)!r})\n'
            'from supervise import run\n'
            f'raise SystemExit(run({command!r}, {str(log)!r}, {str(self.root)!r}, "test", '
            'observer=lambda prefix: []))\n'
        )
        process = subprocess.Popen([sys.executable, '-c', code], start_new_session=True,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        self.processes.append(process)
        return process, log

    def stopped(self, pid):
        try:
            return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] == 'Z'
        except FileNotFoundError:
            return True

    def test_ctrl_c_escalates_when_wine_ignores_it(self):
        command, ready = self.child('wine', ignore_term=False)
        process, log = self.launch(command)
        self.wait_for(ready.exists)
        started = time.monotonic()
        process.send_signal(signal.SIGINT)
        self.assertEqual(process.wait(timeout=6), 130)
        self.assertLess(time.monotonic() - started, 5)
        self.assertTrue(self.stopped(int(ready.read_text())))
        text = log.read_text()
        self.assertIn('Sending SIGTERM', text)
        self.assertNotIn('crash:', text)
        self.assertIn('stop_signal=2', text)

    def test_repeated_ctrl_c_kills_only_this_launch_including_detached_adobe(self):
        command, unrelated_ready = self.child('unrelated', image='Acrobat.exe')
        unrelated = subprocess.Popen(command, executable=sys.executable, start_new_session=True,
                                     env={**os.environ, 'WINEPREFIX': str(self.root),
                                          'ACROBAT_LAUNCH_ID': 'another-launch'})
        self.processes.append(unrelated)
        self.wait_for(unrelated_ready.exists)
        helper_command, helper_ready = self.child('helper', image='AcroCEF.exe')
        command, ready = self.child('wine')
        # A Wine child may setsid(), so it is outside the initial process group.
        command[-1] = (
            'import subprocess, sys\n'
            f'helper = subprocess.Popen({helper_command!r}, executable=sys.executable, start_new_session=True)\n'
            + command[-1]
        )
        process, log = self.launch(command)
        self.wait_for(lambda: ready.exists() and helper_ready.exists())
        helper_pid = int(helper_ready.read_text())
        try:
            process.send_signal(signal.SIGINT)
            self.wait_for(lambda: 'Sending SIGINT' in log.read_text())
            process.send_signal(signal.SIGINT)
            self.assertEqual(process.wait(timeout=5), 130)
            self.wait_for(lambda: self.stopped(helper_pid))
            self.assertTrue(self.stopped(int(ready.read_text())))
            self.assertIsNone(unrelated.poll())
            self.assertIn('Sending SIGKILL', log.read_text())
        finally:
            if not self.stopped(helper_pid):
                os.kill(helper_pid, signal.SIGKILL)

    def test_sigterm_is_bounded_when_child_ignores_termination(self):
        command, ready = self.child('wine')
        process, log = self.launch(command)
        self.wait_for(ready.exists)
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=4), 143)
        self.assertTrue(self.stopped(int(ready.read_text())))
        self.assertIn('Sending SIGKILL', log.read_text())

    def detached_starter(self, command, ready, *, status=0, inherit_output=True):
        return [sys.executable, '-c',
                'import subprocess, sys, time\nfrom pathlib import Path\n'
                f'subprocess.Popen({command!r}, executable=sys.executable, start_new_session=True'
                + (')\n' if inherit_output else ', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n')
                + f'while not Path({str(ready)!r}).exists(): time.sleep(.01)\n'
                + f'raise SystemExit({status})\n']

    def test_ctrl_c_after_original_process_exits_is_bounded(self):
        command, ready = self.child('restarted', image='Acrobat.exe', ignore_term=False)
        process, log = self.launch(self.detached_starter(command, ready))
        self.wait_for(ready.exists)
        pid = int(ready.read_text())
        try:
            time.sleep(.4)
            process.send_signal(signal.SIGINT)
            self.assertEqual(process.wait(timeout=4), 130)
            self.assertTrue(self.stopped(pid))
            self.assertIn('stop_signal=2', log.read_text())
        finally:
            if not self.stopped(pid):
                os.kill(pid, signal.SIGKILL)

    def test_shared_wine_process_holding_output_does_not_delay_normal_close(self):
        server, ready = self.child('server', image='wineserver', ignore_term=False)
        started = time.monotonic()
        process, log = self.launch(self.detached_starter(server, ready, status=1))
        self.wait_for(ready.exists)
        pid = int(ready.read_text())
        try:
            self.assertEqual(process.wait(timeout=3), 1)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertFalse(self.stopped(pid), 'A shared wineserver was terminated')
        finally:
            if not self.stopped(pid):
                os.kill(pid, signal.SIGKILL)

    def test_normal_close_cleans_detached_helpers_and_preserves_another_launch(self):
        command, unrelated_ready = self.child('unrelated', image='Acrobat.exe')
        unrelated = subprocess.Popen(command, executable=sys.executable, start_new_session=True,
                                     env={**os.environ, 'WINEPREFIX': str(self.root),
                                          'ACROBAT_LAUNCH_ID': 'another-launch'})
        self.processes.append(unrelated)
        self.wait_for(unrelated_ready.exists)
        helper, ready = self.child('helper', image='AcroCEF.exe')
        process, log = self.launch(self.detached_starter(helper, ready, status=1))
        self.wait_for(ready.exists)
        pid = int(ready.read_text())
        try:
            started = time.monotonic()
            self.assertEqual(process.wait(timeout=4), 1)
            self.assertLess(time.monotonic() - started, 3)
            self.assertTrue(self.stopped(pid), 'An Adobe helper survived normal close')
            self.assertIsNone(unrelated.poll(), 'Another Acrobat launch was terminated')
            text = log.read_text()
            self.assertIn('remaining Adobe helpers', text)
            self.assertIn('SIGKILL', text)
            self.assertIn('stop_signal=0', text)
            self.assertNotIn('crash:', text)
        finally:
            if not self.stopped(pid):
                os.kill(pid, signal.SIGKILL)

    def test_restarted_acrobat_keeps_bridge_alive_after_original_process_exits(self):
        helper_command, helper_ready = self.child('helper', image='Acrobat.exe', ignore_term=False)
        starter = self.detached_starter(helper_command, helper_ready, inherit_output=False)
        process, log = self.launch(starter)
        self.wait_for(helper_ready.exists)
        helper_pid = int(helper_ready.read_text())
        try:
            time.sleep(5.5)
            self.assertIsNone(process.poll(), 'The bridge exited while its restarted Acrobat was running')
            os.kill(helper_pid, signal.SIGTERM)
            self.assertEqual(process.wait(timeout=4), 0)
        finally:
            if not self.stopped(helper_pid):
                os.kill(helper_pid, signal.SIGKILL)


if __name__ == '__main__':
    unittest.main()
