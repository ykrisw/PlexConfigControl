"""Restore outcome codes follow actual coordinator checkpoints, never log guesses."""
import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from plexconfigcontrol.operations import Phase
from plexconfigcontrol.outcome import describe_outcome
from plexconfigcontrol.startup import reconcile_startup
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.web import Web


class RestoreOutcomeTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        from test_restore_faults import RestoreFaultTests
        with RestoreFaultTests().fixture() as fixture:yield fixture

    def outcome(self,restore):
        with StateStore(restore.state).transaction() as operation:
            return operation.phase,operation.snapshot_id,operation.outcome

    def request(self,app,path):
        from test_runtime import RuntimeTests
        token,_=app.sessions.create()
        status,_,body=RuntimeTests().request(app,path,cookie='pcc_session='+token)
        self.assertEqual(status,'200 OK')
        return json.loads(body)

    def test_success_is_persisted_only_after_reporting_and_snapshot_absence(self):
        from test_restore import NAME
        with self.fixture() as (restore,api,*_):
            restore.run(NAME,'RESTORE')
            phase,snapshot,outcome=self.outcome(restore)
            self.assertEqual((phase,snapshot),(Phase.SUCCESS,None))
            self.assertEqual(outcome,{'code':'RESTORE_COMPLETED','archive':NAME})
            self.assertEqual(api.present,set())
            app=Web(restore.state)
            self.assertEqual(self.request(app,'/api/operation')['operation']['outcome'],outcome)
            self.assertEqual(self.request(app,'/api/recovery')['outcome'],outcome)
            self.assertFalse(any(method in ('app.start','app.stop') for method,_ in api.calls))

    def test_verified_and_unverified_rollback_have_distinct_failed_outcomes(self):
        from test_restore import NAME
        for verified in (False,True):
            with self.subTest(verified=verified),self.fixture() as (restore,api,_,verify,rollback):
                verify.return_value=False;rollback.return_value=verified
                with self.assertRaises(RuntimeError):restore.run(NAME,'RESTORE')
                phase,snapshot,outcome=self.outcome(restore)
                self.assertEqual(phase,Phase.RECOVERY_REQUIRED);self.assertIn(snapshot,api.present)
                self.assertEqual(outcome['code'],'RESTORE_ROLLBACK_VERIFIED' if verified else 'RESTORE_RECOVERY_UNCONFIRMED')
                self.assertEqual(restore.progress.read()['stage'],'CLEANUP_REQUIRED')
                self.assertFalse(any(event['kind']=='RESTORE' and event['status']=='SUCCESS' for event in restore.history.list()))

    def test_failure_before_writes_never_claims_config_was_changed_or_recovered(self):
        from test_restore import NAME
        with self.fixture() as (restore,api,write,*_):
            restore.database_check.side_effect=RuntimeError('invalid staged database')
            with self.assertRaises(RuntimeError):restore.run(NAME,'RESTORE')
            phase,snapshot,outcome=self.outcome(restore)
            self.assertEqual((phase,snapshot),(Phase.FAILED,None))
            self.assertEqual(outcome['code'],'RESTORE_FAILED_UNCHANGED');write.assert_not_called()
            self.assertFalse(any(method.startswith('pool.snapshot.') for method,_ in api.calls))

    def test_reporting_failure_is_not_confused_with_unverified_data_recovery(self):
        from test_restore import NAME
        with self.fixture() as (restore,api,*_):
            original=restore.history.add
            def add(kind,status,*args):
                if kind=='RESTORE' and status=='SUCCESS':raise OSError('History unavailable')
                return original(kind,status,*args)
            with patch.object(restore.history,'add',side_effect=add):
                with self.assertRaises(OSError):restore.run(NAME,'RESTORE')
            phase,snapshot,outcome=self.outcome(restore)
            self.assertEqual((phase,snapshot),(Phase.RECOVERY_REQUIRED,None))
            self.assertEqual(outcome['code'],'RESTORE_VERIFIED_REPORTING_FAILED')
            self.assertEqual(api.present,set())

    def test_lost_snapshot_delete_reply_remains_unconfirmed_not_verified_rollback(self):
        from test_restore import NAME
        with self.fixture() as (restore,api,*_):
            original=api.call
            def call(method,*args):
                result=original(method,*args)
                if method=='pool.snapshot.delete':raise TimeoutError('reply lost')
                return result
            with patch.object(api,'call',side_effect=call):
                with self.assertRaises(TimeoutError):restore.run(NAME,'RESTORE')
            phase,snapshot,outcome=self.outcome(restore)
            self.assertEqual(phase,Phase.RECOVERY_REQUIRED);self.assertIsNotNone(snapshot)
            self.assertEqual(outcome['code'],'RESTORE_RECOVERY_UNCONFIRMED')
            self.assertEqual(api.present,set())

    def test_interruption_during_preparation_is_detected_before_snapshot_or_writes(self):
        from test_restore import NAME
        with self.fixture() as (restore,api,write,*_):
            restore.database_check.side_effect=KeyboardInterrupt('process interrupted')
            with self.assertRaises(KeyboardInterrupt):restore.run(NAME,'RESTORE')
            phase,snapshot,outcome=self.outcome(restore)
            self.assertEqual(phase,Phase.WAITING_FOR_PLEX_STOP);self.assertIsNone(snapshot)
            self.assertEqual(outcome['code'],'RESTORE_IN_PROGRESS')
            calls=list(api.calls)
            result=reconcile_startup(restore.store,restore.progress,restore.history,restore.state)
            self.assertTrue(result['interrupted'])
            phase,snapshot,outcome=self.outcome(restore)
            self.assertEqual(phase,Phase.RECOVERY_REQUIRED);self.assertIsNone(snapshot)
            self.assertEqual(outcome,{'code':'RESTORE_INTERRUPTED','archive':NAME})
            self.assertEqual(api.calls,calls);write.assert_not_called()
            self.assertEqual(restore.progress.read()['stage'],'CLEANUP_REQUIRED')

    def test_normal_manual_stop_wait_survives_restart_without_becoming_execution(self):
        with self.fixture() as (restore,api,write,*_):
            phase,snapshot,outcome=self.outcome(restore)
            self.assertEqual(phase,Phase.WAITING_FOR_PLEX_STOP);self.assertIsNone(outcome)
            self.assertFalse(reconcile_startup(restore.store,restore.progress,restore.history,restore.state)['interrupted'])
            write.assert_not_called();self.assertEqual(api.calls,[])

    def test_cross_kind_outcome_cannot_be_exposed_as_a_restore_result(self):
        from test_restore import NAME
        self.assertIsNone(describe_outcome({'code':'BACKUP_COMPLETED','archive':NAME},'RESTORE'))
        with self.fixture() as (restore,api,*_):
            with restore.store.transaction() as operation:
                operation.outcome={'code':'BACKUP_COMPLETED','archive':NAME}
            app=Web(restore.state)
            self.assertIsNone(self.request(app,'/api/operation')['operation']['outcome'])
            self.assertIsNone(self.request(app,'/api/recovery')['outcome'])


    def test_previous_execution_cannot_be_retried_cancelled_or_marked_ready_without_recovery(self):
        from test_restore import NAME
        from plexconfigcontrol.operations import OperationDenied
        from plexconfigcontrol.restore_readiness import restore_readiness
        from plexconfigcontrol.restore_validation import RestoreValidation
        with self.fixture() as (restore,api,write,*_):
            with restore.store.transaction() as operation:
                operation.outcome={'code':'RESTORE_IN_PROGRESS','archive':NAME}
            with self.assertRaises(OperationDenied):restore.run(NAME,'RESTORE')
            self.assertEqual(api.calls,[]);write.assert_not_called()
            validation=RestoreValidation(restore.destination,restore.state,restore.store,restore.history)
            with self.assertRaises(OperationDenied):validation.cancel()
            readiness=restore_readiness(restore.store,restore.state,api,restore.destination)
            self.assertFalse(readiness['ready']);self.assertEqual(readiness['reason'],'RECOVERY_REQUIRED')
            self.assertFalse(any(method.startswith('pool.snapshot.') for method,_ in api.calls))
