import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import source_tree


class SourceExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'project'
        (self.root / 'packaging').mkdir(parents=True)
        (self.root / 'README.md').write_text('# Example source\n')
        self.names = ['README.md', source_tree.MANIFEST]
        self.manifest()

    def manifest(self, *extra):
        self.names.extend(extra)
        (self.root / source_tree.MANIFEST).write_text('\n'.join(self.names) + '\n')

    def snapshot(self):
        return source_tree.source_snapshot(self.root, check_tree=False)[0]

    def test_export_copies_only_reviewed_bytes_and_preserves_executable_mode(self):
        script = self.root / 'run.sh'
        script.write_text('#!/bin/sh\nexit 0\n')
        script.chmod(0o755)
        self.manifest('run.sh')
        (self.root / 'packaging/payload').mkdir()
        (self.root / 'packaging/payload/private.iso').write_bytes(b'private media')
        snapshot = self.snapshot()
        script.write_text('changed after audit\n')
        output = Path(self.temporary.name) / 'export'
        source_tree.write_snapshot(snapshot, output)
        self.assertEqual((output / 'run.sh').read_text(), '#!/bin/sh\nexit 0\n')
        self.assertEqual((output / 'run.sh').stat().st_mode & 0o777, 0o755)
        self.assertEqual({p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()},
                         set(self.names))
        self.assertFalse((output / 'packaging/payload').exists())

    def test_refuses_existing_destination_without_modifying_it(self):
        snapshot = self.snapshot()
        output = Path(self.temporary.name) / 'export'
        output.mkdir()
        sentinel = output / 'README.md'
        sentinel.write_text('keep me')
        with self.assertRaises(FileExistsError):
            source_tree.write_snapshot(snapshot, output)
        self.assertEqual(sentinel.read_text(), 'keep me')

    def test_rejects_media_and_private_paths_even_if_listed(self):
        for name in ['media.ISO', 'packaging/payload/secret.py', 'prefix/user.reg']:
            with self.subTest(name=name):
                original = self.names[:]
                source = self.root / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text('private input')
                self.manifest(name)
                with self.assertRaises(ValueError):
                    self.snapshot()
                self.names = original
                self.manifest()

    def test_rejects_binary_and_large_files(self):
        source = self.root / 'extra.py'
        self.manifest('extra.py')
        for data in [b'\x00private binary', b'\xff\xfe', b'x' * (source_tree.MAX_FILE_BYTES + 1)]:
            with self.subTest(length=len(data)):
                source.write_bytes(data)
                with self.assertRaises(ValueError):
                    self.snapshot()

    def test_reports_suspected_credentials_without_echoing_values(self):
        source = self.root / 'extra.py'
        self.manifest('extra.py')
        suspect = 'ghp_' + 'a' * 40
        source.write_text('value = ' + repr(suspect))
        with self.assertRaisesRegex(ValueError, 'GitHub token') as caught:
            self.snapshot()
        self.assertNotIn(suspect, str(caught.exception))

    def test_rejects_personal_home_paths(self):
        (self.root / 'README.md').write_text('/' + 'home/' + 'somebody/private-file')
        with self.assertRaisesRegex(ValueError, 'local home path'):
            self.snapshot()

    def test_rejects_symlinks_and_parent_traversal(self):
        (self.root / 'alias.md').symlink_to(self.root / 'README.md')
        self.manifest('alias.md')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            self.snapshot()
        self.names.remove('alias.md')
        self.manifest('../outside.md')
        with self.assertRaisesRegex(ValueError, 'Invalid source path'):
            self.snapshot()

    def test_rejects_unreviewed_visible_or_tracked_files(self):
        with patch.object(source_tree, 'visible_sources', return_value=(set(self.names) | {'notes.txt'}, True)):
            with self.assertRaisesRegex(ValueError, 'Unreviewed.*notes.txt'):
                source_tree.source_snapshot(self.root)

    def test_rejects_listed_source_hidden_by_ignore_rules(self):
        with patch.object(source_tree, 'visible_sources', return_value=({source_tree.MANIFEST}, False)):
            with self.assertRaisesRegex(ValueError, 'hidden by ignore rules.*README.md'):
                source_tree.source_snapshot(self.root)


if __name__ == '__main__':
    unittest.main()
