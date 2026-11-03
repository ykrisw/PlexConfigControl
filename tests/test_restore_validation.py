import io
import tarfile
import tempfile
import unittest
import threading
from unittest.mock import patch
from pathlib import Path
from plexconfigcontrol.archives import REQUIRED, InvalidArchive, validate_archive
from plexconfigcontrol.history import History
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.operations import Phase
from plexconfigcontrol.restore_validation import RestoreValidation
from plexconfigcontrol.progress import Progress
from plexconfigcontrol.locking import OperationBusy

NAME='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'
class RestoreValidationTests(unittest.TestCase):
    def test_background_validation_reserves_lock_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); backup=root/'backup'; backup.mkdir(); (backup/NAME).write_bytes(b'broken')
            state=root/'state'; store=StateStore(state); history=History(state)
            service=RestoreValidation(backup,state,store,history)
            entered=threading.Event(); release=threading.Event()
            def slow_validation(*args,**kwargs):
                entered.set()
                if not release.wait(5): raise RuntimeError('test worker timeout')
                raise InvalidArchive('Corrupt or unreadable archive')
            with patch('plexconfigcontrol.restore_validation.validate_archive',side_effect=slow_validation):
                worker=service.start_background(NAME)
                try:
                    self.assertTrue(entered.wait(5))
                    with store.transaction() as op: self.assertEqual(op.phase,Phase.VALIDATING)
                    with self.assertRaises(OperationBusy): service.start_background(NAME)
                    with self.assertRaises(OperationBusy): service.cancel()
                finally:
                    release.set(); worker.join(5)
                self.assertFalse(worker.is_alive())
            self.assertEqual(Progress(state).read()['stage'],'FAILED')
            with StateStore(state).transaction() as op:
                self.assertEqual(op.phase,Phase.FAILED)
                self.assertEqual(op.validation_details,{'archive':NAME,'status':'FAILED',
                    'reason':'Corrupt or unreadable archive'})
            self.assertEqual(history.list()[0]['status'],'FAILED')

    def test_worker_start_failure_releases_reservation(self):
        with tempfile.TemporaryDirectory() as d:
            store=StateStore(d); service=RestoreValidation(d,d,store,History(d))
            with patch('plexconfigcontrol.restore_validation.threading.Thread.start',side_effect=RuntimeError('no threads')):
                with self.assertRaises(RuntimeError): service.start_background(NAME)
            with store.transaction() as op: self.assertEqual(op.phase,Phase.FAILED)
            self.assertEqual(Progress(d).read()['stage'],'FAILED')
            # A subsequent request obtains the released lock.
            with self.assertRaises(FileNotFoundError): service.validate(NAME)

    def test_validate_wait_and_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); backup=root/'backup'; backup.mkdir(); state=root/'state'
            with tarfile.open(backup/NAME,'w:gz') as archive:
                for name in REQUIRED:
                    member=tarfile.TarInfo(name); member.size=4
                    archive.addfile(member,io.BytesIO(b'test'))
            events=[]
            validate_archive(backup/NAME,progress_callback=lambda stage,done: events.append((stage,done)))
            self.assertIn(('READING_ARCHIVE',4*len(REQUIRED)),events)
            self.assertEqual(events[0],('READING_ARCHIVE',0))
            self.assertEqual(events[-1][0],'CHECKING_GZIP')
            self.assertGreater(events[-1][1],4*len(REQUIRED))
            store=StateStore(state); history=History(state)
            service=RestoreValidation(backup,state,store,history)
            result=service.validate(NAME)
            self.assertEqual(Progress(state).read()['stage'],'WAITING_FOR_PLEX_STOP')
            self.assertIsNone(Progress(state).read()['stage_percent'])
            with store.transaction() as operation:
                self.assertEqual(operation.phase,Phase.WAITING_FOR_PLEX_STOP)
                self.assertEqual(operation.archive_identity,result['sha256'])
                self.assertIsNone(operation.snapshot_id)
                self.assertEqual(operation.validation_details['status'],'VALID')
                self.assertEqual(operation.validation_details['files'],len(REQUIRED))
            service.cancel()
            self.assertEqual(Progress(state).read()['stage'],'CANCELLED')
            self.assertFalse(Progress(state).read()['active'])
            with store.transaction() as operation: self.assertEqual(operation.phase,Phase.IDLE)
            with store.transaction() as operation: self.assertIsNone(operation.validation_details)

    def test_os_error_does_not_expose_host_path_in_result_or_history(self):
        with tempfile.TemporaryDirectory() as d:
            store=StateStore(d); history=History(d)
            service=RestoreValidation(Path(d)/'private-path',d,store,history)
            with self.assertRaises(FileNotFoundError): service.validate(NAME)
            with StateStore(d).transaction() as op:
                self.assertEqual(op.validation_details['reason'],'Archive is unavailable or unreadable')
                self.assertNotIn(d,str(op.validation_details))
            self.assertNotIn('private-path',str(history.detail(history.list()[0]['id'])))
    def test_invalid_archive_leaves_no_active_validation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); backup=root/'backup'; backup.mkdir(); (backup/NAME).write_bytes(b'broken')
            store=StateStore(root/'state'); history=History(root/'state')
            service=RestoreValidation(backup,root/'state',store,history)
            with self.assertRaises(InvalidArchive): service.validate(NAME)
            self.assertEqual(Progress(root/'state').read()['stage'],'FAILED')
            with store.transaction() as operation: self.assertEqual(operation.phase,Phase.FAILED)
