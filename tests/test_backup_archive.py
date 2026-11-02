import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.archives import REQUIRED
from plexconfigcontrol.backup_archive import create_archive, compare_contents, BackupArchiveError

class BackupArchiveTests(unittest.TestCase):
    def test_real_tar_full_verification_and_changed_source_detection(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); snapshot=root/'snapshot'; snapshot.mkdir()
            for name in REQUIRED:
                p=snapshot/name.removeprefix('config/'); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'example')
            (snapshot/'extra.txt').write_bytes(b'extra')
            output=root/'new.tar.gz'
            result=create_archive(snapshot,output)
            self.assertEqual(result.files,4)
            with self.assertRaises(FileExistsError): create_archive(snapshot,output)
            self.assertTrue(output.exists())
            (snapshot/'extra.txt').write_bytes(b'other')
            with self.assertRaises(BackupArchiveError): compare_contents(snapshot,output)
    def test_failed_creation_cleans_only_owned_output(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=root/'source'; source.mkdir(); output=root/'failed.tar.gz'
            class Failed: returncode=2
            with self.assertRaises(BackupArchiveError):
                create_archive(source,output,tar_runner=lambda *args,**kwargs: Failed())
            self.assertFalse(output.exists()); self.assertTrue(source.is_dir())
