import os
import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.storage import RenameRequired, create_destination


class StorageTests(unittest.TestCase):
    def test_existing_folder_and_permissions_untouched_then_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'Plex Config'
            root.mkdir(mode=0o750)
            file=root/'precious.tar.gz'; file.write_bytes(b'keep')
            before=root.stat()
            with self.assertRaises(RenameRequired): create_destination(directory)
            self.assertEqual(root.stat().st_mode,before.st_mode)
            self.assertEqual(root.stat().st_ino,before.st_ino)
            self.assertEqual(file.read_bytes(),b'keep')
            self.assertFalse((root/'Logs').exists())
            root.rename(Path(directory)/'Old Plex Config')
            result=create_destination(directory)
            self.assertTrue(result.logs.is_dir())
            self.assertEqual(result.inode,result.root.stat().st_ino)
            self.assertEqual((Path(directory)/'Old Plex Config'/file.name).read_bytes(),b'keep')

    def test_existing_symlink_rejected_without_writing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'other'; target.mkdir()
            (Path(directory)/'Plex Config').symlink_to(target, target_is_directory=True)
            with self.assertRaises(RenameRequired): create_destination(directory)
            self.assertEqual(list(target.iterdir()),[])

    def test_missing_parent_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory)/'missing'
            with self.assertRaises(FileNotFoundError): create_destination(parent)
            self.assertFalse(parent.exists())
