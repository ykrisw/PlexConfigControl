"""Real GNU tar through a held snapshot fd, with simulated read-only VFS."""
import errno
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from plexconfigcontrol.archives import BASE, validate_archive
from plexconfigcontrol.qnap_archive_capture import capture_snapshot_archive, QnapArchiveCaptureError
from plexconfigcontrol.qnap_snapshot_reader import QnapSnapshotSource
from plexconfigcontrol.staging import stage_archive


class QnapArchiveCaptureTests(unittest.TestCase):
    binary = str(Path(os.environ.get('PCC_TEST_TAR_EXECUTABLE', shutil.which('tar'))).resolve())

    def source(self, parent):
        data = parent/'plex'
        databases = data/'Plug-in Support'/'Databases'
        databases.mkdir(parents=True)
        (data/'Preferences.xml').write_bytes(b'<Preferences/>')
        (databases/'com.plexapp.plugins.library.db').write_bytes(b'library')
        (databases/'com.plexapp.plugins.library.blobs.db').write_bytes(b'blobs')
        return data

    def test_archive_uses_held_directory_even_if_original_path_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            data = self.source(parent)
            fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
            try:
                data.rename(parent/'same-snapshot-new-name')
                self.source(parent)
                (data/'Preferences.xml').write_bytes(b'different-live-file')
                source = QnapSnapshotSource(fd, 'pool/data@fresh')
                calls = []
                def run(argv, **options):
                    calls.append((argv, options['pass_fds']))
                    return subprocess.run(argv, **options)
                output = parent/'result.tar.gz'
                with patch('os.statvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
                    result = capture_snapshot_archive(source, output, self.binary, runner=run)
                self.assertEqual(result.sha256, validate_archive(output).sha256)
                self.assertEqual(calls[0][1], (fd,))
                self.assertIn('--xattrs-include=*', calls[0][0])
                with tarfile.open(output, 'r:gz') as archive:
                    self.assertEqual(archive.extractfile(BASE+'Preferences.xml').read(), b'<Preferences/>')
            finally:
                os.close(fd)

    def test_archive_extracts_portable_layout_with_mode_and_user_xattr(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            data = self.source(parent)
            original = data/'Preferences.xml'
            original.chmod(0o640)
            try:
                os.setxattr(original, 'user.pcc-capture', b'captured-metadata')
            except OSError as error:
                if error.errno in (errno.EPERM, errno.ENOTSUP, errno.ENOSYS, errno.EACCES):
                    self.skipTest('Test filesystem cannot set user xattrs')
                raise
            fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
            output = parent/'result.tar.gz'
            try:
                with patch('os.statvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
                    result = capture_snapshot_archive(QnapSnapshotSource(fd, 'pool/data@fresh'), output, self.binary)
            finally:
                os.close(fd)
            state = parent/'state'
            state.mkdir(mode=0o700)
            with stage_archive(output, state, result.sha256, tar_executable=self.binary) as config:
                restored = config/'Library'/'Application Support'/'Plex Media Server'/'Preferences.xml'
                self.assertEqual(restored.read_bytes(), original.read_bytes())
                self.assertEqual(restored.stat().st_mode & 0o7777, 0o640)
                self.assertEqual(os.getxattr(restored, 'user.pcc-capture'), b'captured-metadata')

    def test_writable_source_is_rejected_before_tar_or_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            data = self.source(parent)
            fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
            output = parent/'result.tar.gz'
            try:
                with patch('os.statvfs', return_value=SimpleNamespace(f_flag=0)), \
                        self.assertRaises(QnapArchiveCaptureError):
                    capture_snapshot_archive(QnapSnapshotSource(fd, 'pool/data@fresh'), output, self.binary,
                        runner=lambda *a, **k: self.fail('Writable source must not reach tar'))
                self.assertFalse(output.exists())
            finally:
                os.close(fd)

    def test_existing_archive_is_never_replaced_or_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            data = self.source(parent)
            fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
            output = parent/'result.tar.gz'
            output.write_bytes(b'previous-archive')
            try:
                with patch('os.statvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
                        self.assertRaises(FileExistsError):
                    capture_snapshot_archive(QnapSnapshotSource(fd, 'pool/data@fresh'), output, self.binary)
                self.assertEqual(output.read_bytes(), b'previous-archive')
            finally:
                os.close(fd)

    def test_nonprivate_workspace_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            data = self.source(parent)
            public = parent/'public'
            public.mkdir(mode=0o755)
            fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with patch('os.statvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
                        self.assertRaises(QnapArchiveCaptureError):
                    capture_snapshot_archive(QnapSnapshotSource(fd, 'pool/data@fresh'), public/'result.tar.gz', self.binary)
            finally:
                os.close(fd)
