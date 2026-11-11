"""Real tar round trips from a native Plex data tree; no NAS calls."""
import tarfile
import tempfile
import unittest
import errno
import os
import struct
from pathlib import Path

from plexconfigcontrol.archives import BASE, validate_archive
from plexconfigcontrol.backup_archive import BackupArchiveError, compare_contents, create_archive
from plexconfigcontrol.staging import stage_archive


class QnapArchiveTests(unittest.TestCase):
    tar_executable = os.environ.get('PCC_TEST_TAR_EXECUTABLE', 'tar')

    def source(self, parent):
        source = parent/'native-plex-data'
        databases = source/'Plug-in Support'/'Databases'
        databases.mkdir(parents=True)
        (source/'Preferences.xml').write_text('<Preferences/>')
        (databases/'com.plexapp.plugins.library.db').write_bytes(b'test library contents')
        (databases/'com.plexapp.plugins.library.blobs.db').write_bytes(b'test blobs contents')
        (source/'Metadata').mkdir()
        (source/'Metadata'/'example').write_bytes(b'artwork contents')
        return source

    def test_native_data_round_trips_through_common_archive_and_staging_format(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = self.source(parent)
            output = parent/'portable.tar.gz'
            result = create_archive(source, output, source_layout='plex-data', tar_executable=self.tar_executable)
            self.assertEqual(validate_archive(output).sha256, result.sha256)
            state = parent/'state'
            state.mkdir()
            with stage_archive(output, state, result.sha256, tar_executable=self.tar_executable) as staged:
                canonical = staged/'Library'/'Application Support'/'Plex Media Server'
                self.assertEqual((canonical/'Metadata'/'example').read_bytes(), b'artwork contents')
                self.assertEqual((canonical/'Preferences.xml').read_bytes(), (source/'Preferences.xml').read_bytes())
            self.assertEqual(list(state.iterdir()), [])
            with tarfile.open(output, 'r:gz') as archive:
                self.assertTrue(all(member.name == BASE.rstrip('/') or member.name.startswith(BASE)
                                    for member in archive))

    def test_changed_source_fails_byte_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = self.source(parent)
            output = parent/'portable.tar.gz'
            create_archive(source, output, source_layout='plex-data', tar_executable=self.tar_executable)
            (source/'Metadata'/'example').write_bytes(b'changed contents')
            with self.assertRaises(BackupArchiveError):
                compare_contents(source, output, source_layout='plex-data')

    def test_unsafe_source_link_is_rejected_and_temporary_archive_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = self.source(parent)
            external = parent/'external'
            external.write_bytes(b'not Plex data')
            (source/'linked').symlink_to(external)
            output = parent/'portable.tar.gz'
            with self.assertRaises(ValueError):
                create_archive(source, output, source_layout='plex-data', tar_executable=self.tar_executable)
            self.assertFalse(output.exists())

    def test_arbitrary_archive_prefix_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            output = parent/'portable.tar.gz'
            with self.assertRaises(BackupArchiveError):
                create_archive(parent, output, source_layout='../elsewhere', tar_executable=self.tar_executable)
            self.assertFalse(output.exists())

    def test_archive_round_trip_retains_xattrs_and_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = self.source(parent)
            original = source/'Metadata'/'example'
            original.chmod(0o640)
            try:
                os.setxattr(original, 'user.pcc-test', b'archive metadata test')
            except OSError as error:
                if error.errno in (errno.ENOTSUP, errno.ENOSYS, errno.EPERM, errno.EACCES):
                    self.skipTest('Test filesystem cannot set user xattrs')
                raise
            output = parent/'portable.tar.gz'
            result = create_archive(source, output, source_layout='plex-data', tar_executable=self.tar_executable)
            state = parent/'state'
            state.mkdir()
            with stage_archive(output, state, result.sha256, tar_executable=self.tar_executable) as staged:
                restored = staged/'Library'/'Application Support'/'Plex Media Server'/'Metadata'/'example'
                self.assertEqual(restored.stat().st_mode & 0o7777, 0o640)
                self.assertEqual(os.getxattr(restored, 'user.pcc-test'), b'archive metadata test')

    def test_archive_round_trip_retains_acl(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = self.source(parent)
            original = source/'Metadata'/'example'
            original.chmod(0o640)
            # Linux POSIX ACL xattr v2: owner, named user, group, mask, other.
            acl = struct.pack('<I', 2)+b''.join(struct.pack('<HHI', *entry) for entry in (
                (1, 6, 0xffffffff), (2, 4, os.getuid()), (4, 4, 0xffffffff),
                (16, 4, 0xffffffff), (32, 0, 0xffffffff)))
            try:
                os.setxattr(original, 'user.pcc-test', b'archive metadata test')
                os.setxattr(original, 'system.posix_acl_access', acl)
            except OSError as error:
                if error.errno in (errno.ENOTSUP, errno.ENOSYS, errno.EPERM, errno.EACCES):
                    self.skipTest('Test filesystem cannot set POSIX ACLs/xattrs')
                raise
            original_acl = os.getxattr(original, 'system.posix_acl_access')
            mode = original.stat().st_mode & 0o7777
            output = parent/'portable.tar.gz'
            result = create_archive(source, output, source_layout='plex-data', tar_executable=self.tar_executable)
            state = parent/'state'
            state.mkdir()
            with stage_archive(output, state, result.sha256, tar_executable=self.tar_executable) as staged:
                restored = staged/'Library'/'Application Support'/'Plex Media Server'/'Metadata'/'example'
                self.assertEqual(restored.read_bytes(), original.read_bytes())
                self.assertEqual(restored.stat().st_mode & 0o7777, mode)
                self.assertEqual(os.getxattr(restored, 'user.pcc-test'), b'archive metadata test')
                self.assertEqual(os.getxattr(restored, 'system.posix_acl_access'), original_acl)
