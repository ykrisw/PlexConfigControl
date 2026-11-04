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
        from plexconfigcontrol.naming import Naming
        for naming in (Naming(),Naming('Moje kopie','Dupa')):
            with tempfile.TemporaryDirectory() as d:
                root=Path(d); state=root/'state'; dest=root/naming.folder_name; (dest/'Logs').mkdir(parents=True)
                source=root/'snapshot'; source.mkdir()
                for name in REQUIRED:
                    p=source/name.removeprefix('config/'); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'test')
                @contextmanager
                def reader(identifier): yield source
                store=StateStore(state); api=API(); history=History(state); progress=Progress(state)
                from plexconfigcontrol.naming import save_naming
                save_naming(state,naming)
                name=Backup(api,store,history,progress,state,dest,'test/config',reader).run_new()
                self.assertTrue(name.startswith(naming.archive_prefix+'_'))
                self.assertTrue((dest/name).is_file()); self.assertEqual(api.present,set())
                self.assertEqual(len(list((dest/'Logs').iterdir())),1)
                with store.transaction() as op: self.assertEqual(op.phase,Phase.SUCCESS)
                self.assertEqual(progress.read()['stage'],'COMPLETED')
                self.assertFalse(any(m in ('app.start','app.stop') for m,_ in api.calls))
    

    def test_unconfirmed_running_plex_blocks_new_and_overwrite_without_mutating_files_or_state(self):
        from unittest.mock import Mock
        from dataclasses import asdict
        from plexconfigcontrol.operations import OperationDenied
        responses = (
            [{'name':'plex','state':'STOPPED'}],
            [{'name':'plex','state':'UNKNOWN'}],
            [{'name':'plex','state':'DEPLOYING'}],
            [{'name':'other-app','state':'RUNNING'}],
            [{'name':'plex','state':'RUNNING'}, {'name':'plex','state':'STOPPED'}],
            None,
            TimeoutError('secret transport details'),
        )
        for overwrite in (False, True):
            for response in responses:
                with self.subTest(overwrite=overwrite,response=response), tempfile.TemporaryDirectory() as directory:
                    root=Path(directory); state=root/'state'; destination=root/'Plex Config'
                    (destination/'Logs').mkdir(parents=True)
                    api=Mock()
                    if isinstance(response,Exception): api.call.side_effect=response
                    else: api.call.return_value=response
                    store=StateStore(state);history=History(state);progress=Progress(state)
                    reader=Mock()
                    backup=Backup(api,store,history,progress,state,destination,'test/config',reader)
                    original=None;selected=None
                    if overwrite:
                        original=destination/'TrueNASPlexConfig_2020.01.01_00.00.00.tar.gz'
                        original.write_bytes(b'preserve existing archive')
                        selected=ArchiveStore(destination,state).list()[0]
                    with store.transaction() as operation: before=asdict(operation)
                    with self.assertRaises(OperationDenied) as error:
                        if overwrite: backup.run_overwrite(selected)
                        else: backup.run_new()
                    self.assertNotIn('secret',str(error.exception))
                    self.assertTrue(all(call.args[0]=='app.query' for call in api.call.call_args_list))
                    reader.assert_not_called()
                    self.assertEqual(list((destination/'Logs').iterdir()),[])
                    self.assertEqual(history.list(),[])
                    self.assertIsNone(progress.read())
                    with store.transaction() as operation: self.assertEqual(asdict(operation),before)
                    if original: self.assertEqual(original.read_bytes(),b'preserve existing archive')

    def test_plex_stopping_after_initial_check_cannot_create_snapshot_or_publish(self):
        from unittest.mock import Mock
        from plexconfigcontrol.operations import OperationDenied
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);state=root/'state';destination=root/'Plex Config'
            (destination/'Logs').mkdir(parents=True)
            api=Mock(); api.call.side_effect=[
                [{'name':'plex','state':'RUNNING'}],
                [{'name':'plex','state':'STOPPING'}],
            ]
            store=StateStore(state);history=History(state);progress=Progress(state)
            reader=Mock()
            backup=Backup(api,store,history,progress,state,destination,'test/config',reader)
            with self.assertRaises(OperationDenied): backup.run_new()
            self.assertEqual([call.args[0] for call in api.call.call_args_list],['app.query','app.query'])
            reader.assert_not_called()
            self.assertEqual(list(destination.glob('*.tar.gz')),[])
            with store.transaction() as operation:
                self.assertEqual(operation.phase,Phase.FAILED)
                self.assertIsNone(operation.snapshot_id)
            self.assertEqual(progress.read()['stage'],'FAILED')
            self.assertEqual(history.list()[0]['status'],'FAILED')
            self.assertEqual(len(list((destination/'Logs').glob('Backup_*.log'))),1)
