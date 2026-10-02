import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import verify_appimage


class Verification(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.image = self.root / "an app's é 100%.AppImage"
        self.image.write_bytes(b'verified application')
        self.digest = hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.cache = self.root / 'cache'

    def verify(self, **kwargs):
        return verify_appimage.verify(self.image, self.digest, self.cache, **kwargs)

    def test_unchanged_image_is_hashed_once(self):
        with patch.object(hashlib, 'file_digest', wraps=hashlib.file_digest) as digest:
            self.assertFalse(self.verify())
            self.assertTrue(self.verify())
            self.assertTrue(self.verify())
            self.assertEqual(digest.call_count, 1)
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o700)
        self.assertEqual(next(self.cache.glob('*.json')).stat().st_mode & 0o777, 0o600)

    def test_in_place_write_with_same_size_and_restored_mtime_is_rejected(self):
        self.verify()
        before = self.image.stat()
        self.image.write_bytes(b'x' * before.st_size)
        os.utime(self.image, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'checksum does not match'):
            self.verify()

    def test_replacement_or_symlink_retarget_cannot_reuse_old_verification(self):
        self.verify()
        replacement = self.root / 'replacement'
        replacement.write_bytes(b'other application')
        replacement.replace(self.image)
        with self.assertRaisesRegex(ValueError, 'checksum does not match'):
            self.verify()
        self.image.unlink()
        self.image.symlink_to(self.root / 'target')
        self.image.resolve().write_bytes(b'verified application')
        self.assertFalse(self.verify())
        self.image.resolve().unlink()
        self.image.resolve().write_bytes(b'other application')
        with self.assertRaisesRegex(ValueError, 'checksum does not match'):
            self.verify()

    def test_new_configured_checksum_requires_new_verification(self):
        self.verify()
        with self.assertRaisesRegex(ValueError, 'checksum does not match'):
            verify_appimage.verify(self.image, '0' * 64, self.cache)

    def test_change_during_hash_is_rejected_and_not_remembered(self):
        actual = hashlib.file_digest

        def replaced(source, algorithm):
            digest = actual(source, algorithm)
            replacement = self.root / 'replacement'
            replacement.write_bytes(b'other application')
            replacement.replace(self.image)
            return digest

        with patch.object(hashlib, 'file_digest', side_effect=replaced):
            with self.assertRaisesRegex(ValueError, 'changed during verification'):
                self.verify()
        self.assertFalse(list(self.cache.glob('*.json')))

    def test_corrupt_cache_is_repaired_only_after_verification(self):
        self.verify()
        entry = next(self.cache.glob('*.json'))
        entry.write_text('not json')
        self.assertFalse(self.verify())
        self.assertEqual(json.loads(entry.read_text())['sha256'], self.digest)

    def test_unavailable_cache_falls_back_to_full_verification(self):
        self.cache.write_text('not a directory')
        with patch.object(hashlib, 'file_digest', wraps=hashlib.file_digest) as digest:
            self.assertFalse(self.verify())
            self.assertFalse(self.verify())
            self.assertEqual(digest.call_count, 2)
        self.image.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum does not match'):
            self.verify()

    def test_shared_or_symlinked_cache_is_not_trusted(self):
        self.verify()
        self.cache.chmod(0o777)
        self.assertFalse(self.verify())
        self.cache.chmod(0o700)
        moved = self.root / 'moved-cache'
        self.cache.rename(moved)
        self.cache.symlink_to(moved, target_is_directory=True)
        self.assertFalse(self.verify())

    def test_always_mode_rehashes_and_does_not_need_a_cache(self):
        self.verify()
        with patch.object(hashlib, 'file_digest', wraps=hashlib.file_digest) as digest:
            self.assertFalse(self.verify(always=True))
            self.assertFalse(self.verify(always=True))
            self.assertEqual(digest.call_count, 2)

    def test_simultaneous_launches_share_one_verification(self):
        context = multiprocessing.get_context('fork')
        hashing = context.Event()
        release = context.Event()
        calls = context.Value('i', 0)
        actual = hashlib.file_digest

        def digest(source, algorithm):
            with calls.get_lock():
                calls.value += 1
            hashing.set()
            if not release.wait(5):
                raise RuntimeError('Test verification was not released')
            return actual(source, algorithm)

        children = []
        try:
            with patch.object(hashlib, 'file_digest', side_effect=digest):
                for _ in range(2):
                    process = context.Process(target=self.verify)
                    process.start()
                    children.append(process)
                self.assertTrue(hashing.wait(5))
                release.set()
                for process in children:
                    process.join(5)
                    self.assertEqual(process.exitcode, 0)
            self.assertEqual(calls.value, 1)
        finally:
            release.set()
            for process in children:
                if process.is_alive():
                    process.terminate()
                process.join(5)


if __name__ == '__main__':
    unittest.main()
