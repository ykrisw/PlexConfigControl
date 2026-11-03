"""Restore fault injection uses temporary real archives and a simulated host."""
import io
import os
import tarfile
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from plexconfigcontrol.archives import REQUIRED
from plexconfigcontrol.eventlog import EventLog
from plexconfigcontrol.history import History
from plexconfigcontrol.operations import Phase
from plexconfigcontrol.progress import Progress
from plexconfigcontrol.restore import Restore
from plexconfigcontrol.restore_validation import RestoreValidation
from plexconfigcontrol.staging import stage_archive
from plexconfigcontrol.startup import reconcile_startup
from plexconfigcontrol.state import StateStore
from test_restore import StoppedAPI, NAME


class RestoreFaultTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);destination=root/'Plex Config';(destination/'Logs').mkdir(parents=True)
            with tarfile.open(destination/NAME,'w:gz') as archive:
                for name in REQUIRED:
                    member=tarfile.TarInfo(name);member.size=4
                    member.uid=os.getuid();member.gid=os.getgid()
                    archive.addfile(member,io.BytesIO(b'test'))
            state=root/'state';store=StateStore(state);history=History(state);progress=Progress(state)
            RestoreValidation(destination,state,store,history).validate(NAME)
            api=StoppedAPI();write=Mock();verify=Mock(return_value=True);rollback=Mock(return_value=True)
            restore=Restore(api,store,history,progress,state,destination,'test/config',
                            Mock(),write,verify,rollback)
            yield restore,api,write,verify,rollback

    def phase(self,restore):
        with restore.store.transaction() as operation:return operation.phase,operation.snapshot_id

    def assert_blocked(self,restore,*,snapshot=True):
        phase,identifier=self.phase(restore)
        self.assertEqual(phase,Phase.RECOVERY_REQUIRED)
        self.assertEqual(bool(identifier),snapshot)
        self.assertEqual(restore.progress.read()['stage'],'CLEANUP_REQUIRED')
        self.assertFalse(restore.progress.read()['active'])
        self.assertFalse(any(row['kind']=='RESTORE' and row['status']=='SUCCESS' for row in restore.history.list()))

    def test_snapshot_removal_only_follows_staging_cleanup(self):
        with self.fixture() as (restore,api,*_):
            cleaned=[]
            @contextmanager
            def stage(*args):
                with stage_archive(*args) as source:yield source
                cleaned.append(True)
            original=api.call
            def call(method,*args):
                if method=='pool.snapshot.delete':self.assertEqual(cleaned,[True])
                return original(method,*args)
            with patch('plexconfigcontrol.restore.stage_archive',stage),patch.object(api,'call',side_effect=call):
                restore.run(NAME,'RESTORE')
            self.assertEqual(self.phase(restore),(Phase.SUCCESS,None))
            self.assertEqual(api.present,set())

    def test_staging_cleanup_failure_retains_snapshot_and_attempts_verified_rollback(self):
        with self.fixture() as (restore,api,write,_,rollback):
            @contextmanager
            def stage(*args):
                with stage_archive(*args) as source:yield source
                raise OSError('injected staging cleanup failure')
            with patch('plexconfigcontrol.restore.stage_archive',stage):
                with self.assertRaisesRegex(OSError,'staging cleanup failure'):restore.run(NAME,'RESTORE')
            self.assert_blocked(restore)
            self.assertTrue(api.present);write.assert_called_once();rollback.assert_called_once()
            self.assertFalse(any(method=='pool.snapshot.delete' for method,_ in api.calls))

    def test_progress_error_must_not_prevent_rollback(self):
        with self.fixture() as (restore,api,write,_,rollback):
            write.side_effect=RuntimeError('original write failed')
            update=restore.progress.update
            def progress(stage,*args,**kwargs):
                if stage=='ROLLING_BACK':raise OSError('progress database unavailable')
                return update(stage,*args,**kwargs)
            with patch.object(restore.progress,'update',side_effect=progress):
                with self.assertRaisesRegex(RuntimeError,'original write failed'):restore.run(NAME,'RESTORE')
            rollback.assert_called_once();self.assert_blocked(restore)
            self.assertTrue(any(method=='pool.snapshot.rollback' for method,_ in api.calls))

    def test_success_history_failure_clears_completed_progress_without_editing_closed_log(self):
        with self.fixture() as (restore,api,*_):
            original=restore.history.add;closed_log=[];finished=[]
            def add(kind,status,*args):
                if kind=='RESTORE' and status=='SUCCESS':
                    path=next((restore.destination/'Logs').glob('Restore_*.log'))
                    closed_log.append((path,path.read_bytes()))
                    finished.append(restore.progress.read()['finished'])
                    raise OSError('history write failed')
                return original(kind,status,*args)
            with patch.object(restore.history,'add',side_effect=add):
                with self.assertRaisesRegex(OSError,'history write failed'):restore.run(NAME,'RESTORE')
            self.assert_blocked(restore,snapshot=False)
            self.assertEqual(restore.progress.read()['finished'],finished[0])
            self.assertEqual(closed_log[0][0].read_bytes(),closed_log[0][1])
            recovery=next((restore.destination/'Logs').glob('Recovery_*.log')).read_text()
            self.assertIn('final operation reporting failed',recovery)
            self.assertEqual(api.present,set())

    def test_total_history_failure_does_not_mask_original_error_or_leave_success(self):
        with self.fixture() as (restore,api,*_):
            with patch.object(restore.history,'add',side_effect=OSError('history unavailable')):
                with self.assertRaisesRegex(OSError,'history unavailable'):restore.run(NAME,'RESTORE')
            self.assert_blocked(restore,snapshot=False)
            self.assertTrue(list((restore.destination/'Logs').glob('Recovery_*.log')))
            self.assertEqual(api.present,set())

    def test_log_failure_after_snapshot_creation_preserves_snapshot_without_writing_config(self):
        with self.fixture() as (restore,api,write,*_):
            with patch.object(EventLog,'write',side_effect=OSError('permanent log failed')):
                with self.assertRaisesRegex(OSError,'permanent log failed'):restore.run(NAME,'RESTORE')
            self.assert_blocked(restore);write.assert_not_called()
            self.assertTrue(api.present)
            self.assertFalse(any(method in ('pool.snapshot.rollback','pool.snapshot.delete') for method,_ in api.calls))

    def test_delete_reply_loss_does_not_claim_snapshot_still_exists(self):
        with self.fixture() as (restore,api,*_):
            original=api.call
            def call(method,*args):
                result=original(method,*args)
                if method=='pool.snapshot.delete':raise TimeoutError('deletion reply lost')
                return result
            with patch.object(api,'call',side_effect=call):
                with self.assertRaisesRegex(TimeoutError,'deletion reply lost'):restore.run(NAME,'RESTORE')
            self.assert_blocked(restore)
            self.assertEqual(api.present,set())
            body=next((restore.destination/'Logs').glob('Restore_*.log')).read_text()
            self.assertIn('presence requires verification',body)
            self.assertNotIn('Rollback verified.',body)
            self.assertFalse(any(method=='pool.snapshot.rollback' for method,_ in api.calls))

    def test_failed_snapshot_deletion_with_existing_point_rolls_back_and_retains_it(self):
        with self.fixture() as (restore,api,_,_,rollback):
            api.keep=True
            with self.assertRaises(RuntimeError):restore.run(NAME,'RESTORE')
            self.assert_blocked(restore);rollback.assert_called_once()
            self.assertTrue(api.present)
            self.assertTrue(any(method=='pool.snapshot.rollback' for method,_ in api.calls))

    def test_plex_started_during_staging_cleanup_is_not_automatically_stopped(self):
        with self.fixture() as (restore,api,*_):
            started=[];original=api.call
            @contextmanager
            def stage(*args):
                with stage_archive(*args) as source:yield source
                started.append(True)
            def call(method,*args):
                if method=='app.query' and started:
                    api.calls.append((method,args));return [{'name':'plex','state':'RUNNING'}]
                return original(method,*args)
            with patch('plexconfigcontrol.restore.stage_archive',stage),patch.object(api,'call',side_effect=call):
                with self.assertRaises(RuntimeError):restore.run(NAME,'RESTORE')
            self.assert_blocked(restore)
            self.assertFalse(any(method in ('app.start','app.stop','pool.snapshot.delete','pool.snapshot.rollback') for method,_ in api.calls))

    def test_interrupted_finalization_does_not_leave_completed_progress_after_restart(self):
        with self.fixture() as (restore,api,*_):
            with restore.store.transaction() as operation:operation.phase=Phase.RUNNING
            restore.progress.start('RESTORE',now=100)
            restore.progress.update('COMPLETED',now=125)
            reconcile_startup(restore.store,restore.progress,restore.history,restore.state)
            self.assert_blocked(restore,snapshot=False)
            self.assertEqual(restore.progress.read(now=1000)['elapsed_seconds'],25)
            self.assertEqual(api.calls,[])

    def test_process_interruption_retains_snapshot_for_startup_reconciliation(self):
        with self.fixture() as (restore,api,_,verify,_):
            verify.side_effect=KeyboardInterrupt('simulated process interruption')
            with self.assertRaises(KeyboardInterrupt):restore.run(NAME,'RESTORE')
            phase,identifier=self.phase(restore)
            self.assertEqual(phase,Phase.RUNNING);self.assertIn(identifier,api.present)
            log=next((restore.destination/'Logs').glob('Restore_*.log'));before=log.read_bytes()
            reconcile_startup(restore.store,restore.progress,restore.history,restore.state)
            self.assert_blocked(restore)
            self.assertEqual(log.read_bytes(),before)
            self.assertFalse(any(method in ('app.start','app.stop','pool.snapshot.delete','pool.snapshot.rollback') for method,_ in api.calls))


    def test_lost_snapshot_creation_reply_blocks_without_writing_or_creating_another_point(self):
        with self.fixture() as (restore,api,write,*_):
            api.fail_create=True
            with self.assertRaises(TimeoutError):restore.run(NAME,'RESTORE')
            self.assert_blocked(restore);write.assert_not_called()
            self.assertEqual(len(api.present),1)
            self.assertEqual(sum(method=='pool.snapshot.create' for method,_ in api.calls),1)
            self.assertFalse(any(method in ('pool.snapshot.delete','pool.snapshot.rollback') for method,_ in api.calls))

    def test_remaining_private_workspace_blocks_even_when_config_was_not_modified(self):
        with self.fixture() as (restore,api,write,*_):
            def invalid_database(_):
                (restore.state/'restore-leftover-fixture').mkdir()
                raise RuntimeError('invalid staged database')
            restore.database_check=invalid_database
            with self.assertRaisesRegex(RuntimeError,'invalid staged database'):restore.run(NAME,'RESTORE')
            self.assert_blocked(restore,snapshot=False);write.assert_not_called()
            self.assertEqual(api.present,set())
            self.assertFalse(any(method=='pool.snapshot.create' for method,_ in api.calls))
            self.assertTrue((restore.state/'restore-leftover-fixture').exists())
