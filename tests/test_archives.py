import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.archives import REQUIRED, InvalidArchive, backup_action, validate_archive

class ArchiveTests(unittest.TestCase):
    def make(self, path, extra=None):
        with tarfile.open(path, 'w:gz') as archive:
            for name in sorted(REQUIRED) + ([extra] if extra else []):
                member = tarfile.TarInfo(name)
                member.size = 4
                archive.addfile(member, io.BytesIO(b'test'))

    def test_current_count(self):
        self.assertEqual([backup_action(n) for n in (0,1,2,1)], ['CREATE_NEW','ASK_OVERWRITE_OR_NEW','CREATE_NEW','ASK_OVERWRITE_OR_NEW'])

    def test_full_read(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.tar.gz'; self.make(p)
            self.assertEqual(validate_archive(p).bytes_read,12)

    def test_unsafe_and_truncated(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.tar.gz'; self.make(p,'config/../../outside')
            with self.assertRaises(InvalidArchive): validate_archive(p)
            self.make(p); p.write_bytes(p.read_bytes()[:-5])
            with self.assertRaises(InvalidArchive): validate_archive(p)
