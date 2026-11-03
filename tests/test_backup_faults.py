"""Actual tar/gzip publication with simulated host and injected reporting faults."""
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from plexconfigcontrol import publication_intent as intent
from plexconfigcontrol.eventlog import EventLog
from plexconfigcontrol.operations import OperationDenied, Phase
from plexconfigcontrol.publication_recovery import PublicationRecovery
from plexconfigcontrol.publish import publish_new

NEW='TrueNASPlexConfig_2026.11.03_12.00.00.tar.gz'


class BackupFaultTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        # Keep this import local: do not rediscover another unittest class here.
        from test_backup_overwrite import ReplacementTests
        with ReplacementTests().fixture() as fixture:yield fixture

    def phase(self,store):
        with store.transaction() as operation:return operation.phase,operation.snapshot_id

    def assert_no_plex_control(self,api):
        self.assertFalse(any(method in ('app.start','app.stop') for method,_ in api.calls))
        self.assertEqual(sum(method=='pool.snapshot.create' for method,_ in api.calls),1)

    def test_history_failure_preserves_publication_digest_and_allows_confirmed_recovery(self):
        for overwrite in (False,True):
            with self.subTest(overwrite=overwrite),self.fixture() as fixture:
                backup,selected,old,api,store,history,progress=fixture
                original=history.add;closed=[];finished=[]
                def add(kind,status,*args):
                    if kind=='BACKUP' and status=='SUCCESS':
                        path=next((backup.destination/'Logs').glob('Backup_*.log'))
                        closed.append((path,path.read_bytes()));finished.append(progress.read()['finished'])
                        raise OSError('history unavailable')
                    return original(kind,status,*args)
                with patch.object(history,'add',side_effect=add):
                    with self.assertRaisesRegex(OSError,'history unavailable'):
                        if overwrite:backup.run_overwrite(selected)
                        else:backup.run_new(create_another=selected)
                self.assertEqual(self.phase(store),(Phase.RECOVERY_REQUIRED,None))
                self.assertEqual(progress.read()['stage'],'CLEANUP_REQUIRED')
                self.assertEqual(progress.read()['finished'],finished[0])
                self.assertEqual(closed[0][0].read_bytes(),closed[0][1])
                self.assertTrue((backup.destination/NEW).exists())
                self.assertEqual(old.exists(),not overwrite)
                self.assertEqual(api.present,set());self.assert_no_plex_control(api)
                self.assertTrue(intent.pending(backup.state))
                recovery=PublicationRecovery(store,history,progress,backup.state,backup.destination)
                report=recovery.inspect();before=list(api.calls)
                # Failure reporting already created a Recovery log this second.
                # Pick another timestamp; permanent logs must never be replaced.
                with patch('plexconfigcontrol.publication_recovery.datetime') as clock:
                    clock.now.return_value=datetime(2030,1,1,tzinfo=timezone.utc)
                    recovery.keep_archives(report['confirmation_token'],confirmed=True)
                self.assertFalse(intent.pending(backup.state))
                self.assertEqual(self.phase(store),(Phase.FAILED,None))
                self.assertEqual(api.calls,before)
                self.assertFalse(any(row['status']=='SUCCESS' for row in history.list()))

    def test_total_history_failure_does_not_mask_error_or_keep_completed_progress(self):
        with self.fixture() as (backup,selected,old,api,store,history,progress):
            with patch.object(history,'add',side_effect=OSError('history down')):
                with self.assertRaisesRegex(OSError,'history down'):backup.run_new(create_another=selected)
            self.assertEqual(self.phase(store),(Phase.RECOVERY_REQUIRED,None))
            self.assertEqual(progress.read()['stage'],'CLEANUP_REQUIRED')
            self.assertTrue(old.exists());self.assertTrue((backup.destination/NEW).exists())
            self.assertTrue(intent.pending(backup.state))
            self.assertTrue(list((backup.destination/'Logs').glob('Recovery_*.log')))
            self.assert_no_plex_control(api)

    def test_failed_cleanup_preserves_old_archive_before_retirement(self):
        with self.fixture() as (backup,selected,old,api,store,history,progress):
            temporary_directory=tempfile.TemporaryDirectory
            @contextmanager
            def cleanup_failure(*args,**kwargs):
                with temporary_directory(*args,**kwargs) as workspace:yield workspace
                raise OSError('workspace cleanup failed')
            with patch('plexconfigcontrol.backup.tempfile.TemporaryDirectory',cleanup_failure):
                with self.assertRaisesRegex(OSError,'workspace cleanup failed'):backup.run_overwrite(selected)
            self.assertTrue(old.exists());self.assertTrue((backup.destination/NEW).exists())
            self.assertEqual(self.phase(store),(Phase.RECOVERY_REQUIRED,None))
            self.assertTrue(intent.pending(backup.state))
            self.assertEqual(api.present,set());self.assert_no_plex_control(api)

    def test_remaining_workspace_cannot_be_dismissed_by_publication_recovery(self):
        with self.fixture() as (backup,selected,old,api,store,history,progress):
            temporary_directory=tempfile.TemporaryDirectory
            @contextmanager
            def cleanup_leftover(*args,**kwargs):
                with temporary_directory(*args,**kwargs) as workspace:yield workspace
                (backup.state/'backup-leftover-fixture').mkdir()
            with patch('plexconfigcontrol.backup.tempfile.TemporaryDirectory',cleanup_leftover):
                with self.assertRaisesRegex(RuntimeError,'cleanup requires verification'):backup.run_overwrite(selected)
            recovery=PublicationRecovery(store,history,progress,backup.state,backup.destination)
            with self.assertRaises(OperationDenied):recovery.inspect()
            self.assertTrue((backup.state/'backup-leftover-fixture').exists())
            self.assertTrue(old.exists());self.assertTrue(intent.pending(backup.state))

    def test_failed_log_write_after_snapshot_creation_still_removes_exact_snapshot(self):
        with self.fixture() as (backup,selected,old,api,store,history,progress):
            original=EventLog.write
            def write(log,message,*args,**kwargs):
                if message.startswith('Temporary snapshot created:'):raise OSError('log storage failed')
                return original(log,message,*args,**kwargs)
            with patch.object(EventLog,'write',write):
                with self.assertRaisesRegex(OSError,'log storage failed'):backup.run_new(create_another=selected)
            self.assertEqual(api.present,set())
            self.assertEqual(self.phase(store),(Phase.FAILED,None))
            self.assertEqual(progress.read()['stage'],'FAILED')
            self.assertTrue(old.exists());self.assertFalse((backup.destination/NEW).exists())
            self.assert_no_plex_control(api)
            self.assertEqual(sum(method=='pool.snapshot.delete' for method,_ in api.calls),1)

    def test_failed_snapshot_cleanup_stays_blocked_and_creates_no_final_archive(self):
        with self.fixture() as (backup,selected,old,api,store,history,progress):
            api.keep=True
            with self.assertRaises(RuntimeError):backup.run_new(create_another=selected)
            phase,identifier=self.phase(store)
            self.assertEqual(phase,Phase.RECOVERY_REQUIRED);self.assertIn(identifier,api.present)
            self.assertEqual(progress.read()['stage'],'CLEANUP_REQUIRED')
            self.assertFalse((backup.destination/NEW).exists());self.assertTrue(old.exists())
            self.assertFalse(list(backup.state.glob('backup-*')))
            self.assert_no_plex_control(api)

    def test_publication_exception_after_final_link_retains_file_and_marker(self):
        with self.fixture() as (backup,selected,old,api,store,history,progress):
            def ambiguous(*args):
                publish_new(*args)
                raise OSError('reply lost after link')
            with patch('plexconfigcontrol.backup.publish_new',side_effect=ambiguous):
                with self.assertRaisesRegex(OSError,'reply lost after link'):backup.run_new(create_another=selected)
            self.assertTrue((backup.destination/NEW).exists());self.assertTrue(old.exists())
            self.assertTrue(intent.pending(backup.state))
            self.assertEqual(self.phase(store),(Phase.RECOVERY_REQUIRED,None))
            report=PublicationRecovery(store,history,progress,backup.state,backup.destination).inspect()
            self.assertEqual(report['archive'],NEW);self.assert_no_plex_control(api)

    def test_lost_snapshot_creation_reply_cleans_up_without_a_second_snapshot(self):
        with self.fixture() as (backup,selected,old,api,store,history,progress):
            api.fail_create=True
            with self.assertRaises(TimeoutError):backup.run_new(create_another=selected)
            self.assertEqual(api.present,set());self.assertEqual(self.phase(store),(Phase.FAILED,None))
            self.assertFalse((backup.destination/NEW).exists());self.assertTrue(old.exists())
            self.assert_no_plex_control(api)

    def test_marker_recreation_failure_keeps_recovery_blocked_without_deleting_archive(self):
        with self.fixture() as (backup,selected,old,api,store,history,progress):
            original=intent.record;calls=[]
            def record(*args,**kwargs):
                calls.append(True)
                if len(calls)>1:raise OSError('intent storage failed')
                return original(*args,**kwargs)
            original_add=history.add
            def add(kind,status,*args):
                if status=='SUCCESS':raise RuntimeError('original reporting failure')
                return original_add(kind,status,*args)
            with patch.object(intent,'record',side_effect=record),patch.object(history,'add',side_effect=add):
                with self.assertRaisesRegex(RuntimeError,'original reporting failure'):backup.run_new(create_another=selected)
            self.assertEqual(self.phase(store),(Phase.RECOVERY_REQUIRED,None))
            self.assertEqual(progress.read()['stage'],'CLEANUP_REQUIRED')
            self.assertTrue(old.exists());self.assertTrue((backup.destination/NEW).exists())
            self.assertFalse(intent.pending(backup.state))


    def test_interruption_during_final_reporting_is_blocked_after_restart(self):
        from plexconfigcontrol.startup import reconcile_startup
        with self.fixture() as (backup,selected,old,api,store,history,progress):
            original=EventLog.write
            def write(log,message,*args,**kwargs):
                if message.startswith('Backup completed successfully:'):
                    raise KeyboardInterrupt('interrupted final reporting')
                return original(log,message,*args,**kwargs)
            with patch.object(EventLog,'write',write):
                with self.assertRaises(KeyboardInterrupt):backup.run_new(create_another=selected)
            self.assertEqual(self.phase(store),(Phase.RUNNING,None))
            self.assertTrue((backup.destination/NEW).exists());self.assertTrue(old.exists())
            self.assertEqual(api.present,set())
            log=next((backup.destination/'Logs').glob('Backup_*.log'));before=log.read_bytes()
            calls=list(api.calls)
            reconcile_startup(store,progress,history,backup.state)
            self.assertEqual(self.phase(store),(Phase.RECOVERY_REQUIRED,None))
            self.assertEqual(progress.read()['stage'],'CLEANUP_REQUIRED')
            self.assertEqual(log.read_bytes(),before);self.assertEqual(api.calls,calls)
            self.assertFalse(any(row['kind']=='BACKUP' and row['status']=='SUCCESS' for row in history.list()))
