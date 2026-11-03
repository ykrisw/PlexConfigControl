import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from plexconfigcontrol.snapshot_reader import SnapshotReader,SnapshotReadError

NAME='pcc-backup-'+'a'*32
class API:
    def call(self,method,filters): return [{'id':filters[0][2]}]

class ReaderTests(unittest.TestCase):
    def test_exact_snapshot_only_and_fd_closed_after_context(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); snapshot=root/'.zfs/snapshot'/NAME; snapshot.mkdir(parents=True)
            (snapshot/'test').write_text('immutable example'); info=root.stat()
            reader=SnapshotReader(root,'test/config',info.st_dev,info.st_ino,API())
            with patch('plexconfigcontrol.snapshot_reader.os.statvfs',return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
                with reader('test/config@'+NAME) as path:
                    self.assertEqual((path/'test').read_text(),'immutable example')
                    self.assertEqual(path,snapshot)
                self.assertTrue(snapshot.exists())
            with self.assertRaises(SnapshotReadError):
                with reader('other/config@'+NAME): pass
    def test_live_directory_is_never_used_as_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'live.txt').write_text('live'); info=root.stat()
            reader=SnapshotReader(root,'test/config',info.st_dev,info.st_ino,API())
            with self.assertRaises(SnapshotReadError):
                with reader('test/config@'+NAME): self.fail('Must not expose live config')
    def test_writable_source_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'.zfs/snapshot'/NAME).mkdir(parents=True); info=root.stat()
            reader=SnapshotReader(root,'test/config',info.st_dev,info.st_ino,API())
            with patch('plexconfigcontrol.snapshot_reader.os.statvfs',return_value=SimpleNamespace(f_flag=0)):
                with self.assertRaises(SnapshotReadError):
                    with reader('test/config@'+NAME): pass

    def test_malformed_snapshot_results_never_expose_a_source_directory(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'.zfs/snapshot'/NAME).mkdir(parents=True);info=root.stat()
            for answer in (None,{},[None],[False],[{'id':'other/config@'+NAME}]):
                api=Mock();api.call.return_value=answer
                reader=SnapshotReader(root,'test/config',info.st_dev,info.st_ino,api)
                with self.subTest(answer=answer):
                    with self.assertRaises(SnapshotReadError):
                        with reader('test/config@'+NAME): self.fail('No source may be exposed')
