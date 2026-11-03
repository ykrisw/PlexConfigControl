import tempfile
import unittest
from pathlib import Path
from contextlib import contextmanager
from plexconfigcontrol.backup import Backup, BackupDecisionRequired
from plexconfigcontrol.archive_store import ArchiveStore, ArchiveChanged
from plexconfigcontrol.archives import REQUIRED
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.history import History
from plexconfigcontrol.progress import Progress
from plexconfigcontrol.operations import Phase
from test_snapshots import API

class BackupTests(unittest.TestCase):
    def test_single_copy_requires_current_explicit_decision(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); state=root/'state'; dest=root/'Plex Config'; (dest/'Logs').mkdir(parents=True)
            existing=dest/'TrueNASPlexConfig_2020.01.01_00.00.00.tar.gz'
            existing.write_bytes(b'old copy')
            source=root/'snapshot'; source.mkdir()
            for name in REQUIRED:
                p=source/name.removeprefix('config/'); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'test')
            @contextmanager
            def reader(identifier): yield source
            store=StateStore(state); api=API(); history=History(state); progress=Progress(state)
            backup=Backup(api,store,history,progress,state,dest,'test/config',reader)
            with self.assertRaises(BackupDecisionRequired) as question:
                backup.run_new()
            self.assertEqual(api.calls,[])
            self.assertEqual(list((dest/'Logs').iterdir()),[])
            with store.transaction() as op: self.assertEqual(op.phase,Phase.IDLE)
            selected=question.exception.archive
            existing.write_bytes(b'externally changed old copy')
            with self.assertRaises(ArchiveChanged): backup.run_new(create_another=selected)
            self.assertEqual(api.calls,[])
            current=ArchiveStore(dest,state).list()[0]
            name=backup.run_new(create_another=current)
            self.assertEqual(existing.read_bytes(),b'externally changed old copy')
            self.assertTrue((dest/name).is_file())
            self.assertEqual(len(ArchiveStore(dest,state).list()),2)
            # Returning to one archive must bring the question back.
            (dest/name).unlink()
            with self.assertRaises(BackupDecisionRequired): backup.run_new()

    def test_full_new_backup_with_real_archive_and_fake_host(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); state=root/'state'; dest=root/'Plex Config'; (dest/'Logs').mkdir(parents=True)
            source=root/'snapshot'; source.mkdir()
            for name in REQUIRED:
                p=source/name.removeprefix('config/'); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'test')
            @contextmanager
            def reader(identifier): yield source
            store=StateStore(state); api=API(); history=History(state); progress=Progress(state)
            name=Backup(api,store,history,progress,state,dest,'test/config',reader).run_new()
            self.assertTrue((dest/name).is_file()); self.assertEqual(api.present,set())
            self.assertEqual(len(list((dest/'Logs').iterdir())),1)
            with store.transaction() as op: self.assertEqual(op.phase,Phase.SUCCESS)
            self.assertEqual(progress.read()['stage'],'COMPLETED')
            self.assertFalse(any(m in ('app.start','app.stop') for m,_ in api.calls))
