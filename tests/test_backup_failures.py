import tempfile
import unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
from plexconfigcontrol.backup import Backup
from plexconfigcontrol.archives import REQUIRED
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.history import History
from plexconfigcontrol.progress import Progress
from plexconfigcontrol.operations import Phase, OperationDenied
from test_snapshots import API

class BackupFailureTests(unittest.TestCase):
    def prepare(self,directory):
        root=Path(directory); state=root/'state'; dest=root/'Plex Config'
        (dest/'Logs').mkdir(parents=True); source=root/'snapshot'; source.mkdir()
        for name in REQUIRED:
            p=source/name.removeprefix('config/'); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'test')
        @contextmanager
        def reader(identifier): yield source
        store=StateStore(state); api=API(); history=History(state); progress=Progress(state)
        runner=Backup(api,store,history,progress,state,dest,'test/config',reader)
        return root,store,api,history,progress,runner

    def test_archive_failure_cleans_snapshot_and_preserves_old_archive(self):
        with tempfile.TemporaryDirectory() as d:
            root,store,api,history,progress,runner=self.prepare(d)
            old=root/'Plex Config'/'existing.tar.gz'; old.write_bytes(b'keep')
            with patch('plexconfigcontrol.backup.create_archive',side_effect=OSError('disk full')):
                with self.assertRaises(OSError): runner.run_new()
            self.assertEqual(api.present,set()); self.assertEqual(old.read_bytes(),b'keep')
            with store.transaction() as op: self.assertEqual(op.phase,Phase.FAILED)
            self.assertEqual(progress.read()['stage'],'FAILED')
            self.assertEqual(history.list()[0]['status'],'FAILED')
            self.assertEqual(list((root/'state').glob('backup-*')),[])

    def test_failed_snapshot_cleanup_blocks_next_backup_and_publication(self):
        with tempfile.TemporaryDirectory() as d:
            root,store,api,history,progress,runner=self.prepare(d); api.keep=True
            with self.assertRaises(Exception): runner.run_new()
            self.assertEqual(list((root/'Plex Config').glob('*.tar.gz')),[])
            with store.transaction() as op:
                self.assertEqual(op.phase,Phase.RECOVERY_REQUIRED)
                self.assertIn(op.snapshot_id,api.present)
            self.assertEqual(progress.read()['stage'],'CLEANUP_REQUIRED')
            with self.assertRaises(OperationDenied): runner.run_new()

    def test_lost_create_reply_is_reconciled_before_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root,store,api,history,progress,runner=self.prepare(d); api.fail_create=True
            with self.assertRaises(TimeoutError): runner.run_new()
            self.assertEqual(api.present,set())
            with store.transaction() as op:
                self.assertIsNone(op.snapshot_id); self.assertEqual(op.phase,Phase.FAILED)
            self.assertEqual(list((root/'Plex Config').glob('*.tar.gz')),[])

    def test_failed_publication_retains_recovery_block(self):
        with tempfile.TemporaryDirectory() as d:
            root,store,api,history,progress,runner=self.prepare(d)
            def fail(source,dest,name,digest,callback):
                callback('.pcc-' + 'a'*32 + '.tmp')
                raise OSError('publication failed')
            with patch('plexconfigcontrol.backup.publish_new',side_effect=fail):
                with self.assertRaises(OSError): runner.run_new()
            self.assertEqual(api.present,set())
            with store.transaction() as op:
                self.assertEqual(op.phase,Phase.RECOVERY_REQUIRED)
            self.assertTrue((root/'state'/'publication-intent.txt').exists())
