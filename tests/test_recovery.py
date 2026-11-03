import tempfile
import unittest
from plexconfigcontrol.history import History
from plexconfigcontrol.locking import operation_lock, OperationBusy
from plexconfigcontrol.operations import OperationDenied, Phase
from plexconfigcontrol.recovery import Recovery
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.snapshots import Snapshots
from test_snapshots import API

class RecoveryTests(unittest.TestCase):
    def setup_recovery(self, directory):
        store=StateStore(directory); api=API(); history=History(directory)
        with store.transaction() as op:
            op.begin('BACKUP'); op.begin_backup()
        identifier=Snapshots(api,store,'test/config').create()
        with store.transaction() as op: op.finish(False)
        return store, api, Recovery(api,store,history,directory,'test/config'), identifier

    def test_confirmation_and_identity_required(self):
        with tempfile.TemporaryDirectory() as d:
            store,api,recovery,identifier=self.setup_recovery(d)
            with self.assertRaises(OperationDenied): recovery.remove_snapshot(identifier)
            with self.assertRaises(OperationDenied): recovery.remove_snapshot(identifier+'x',True)
            self.assertIn(identifier,api.present)

    def test_busy_operation_prevents_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            store,api,recovery,identifier=self.setup_recovery(d)
            with operation_lock(d):
                with self.assertRaises(OperationBusy): recovery.remove_snapshot(identifier,True)
            self.assertIn(identifier,api.present)

    def test_removal_does_not_report_original_success_or_unblock_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            store,api,recovery,identifier=self.setup_recovery(d)
            result=recovery.remove_snapshot(identifier,True)
            self.assertTrue(result['cleanup_required'])
            self.assertNotIn(identifier,api.present)
            with store.transaction() as op:
                self.assertIsNone(op.snapshot_id)
                self.assertEqual(op.phase,Phase.RECOVERY_REQUIRED)
                with self.assertRaises(OperationDenied): op.begin('BACKUP')

    def test_inspection_confirms_exact_snapshot_without_mutations_or_history_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            store,api,recovery,identifier=self.setup_recovery(directory)
            before=recovery.history.list();api.calls.clear()
            result=recovery.inspect()
            self.assertEqual(result['snapshot_state'],'PRESENT')
            self.assertEqual(result['snapshot_id'],identifier)
            self.assertTrue(result['removal_available'])
            self.assertTrue(result['confirmation_required'])
            self.assertFalse(result['loses_restore_recovery_point'])
            self.assertEqual(recovery.history.list(),before)
            self.assertEqual(api.calls,[('pool.snapshot.query',([['id','=',identifier]],))])
            self.assertIn(identifier,api.present)

    def test_malformed_queries_never_enable_removal_or_clear_retained_identity(self):
        from unittest.mock import patch
        from plexconfigcontrol.snapshots import SnapshotError
        for answer in (None,{},False,'', [None], [{'id':'other/config@unrelated'}],
                       [{'id':'duplicate'},{'id':'duplicate'}]):
            with self.subTest(answer=answer),tempfile.TemporaryDirectory() as directory:
                store,api,recovery,identifier=self.setup_recovery(directory)
                with patch.object(api,'call',return_value=answer) as call:
                    result=recovery.inspect()
                    self.assertEqual(result['snapshot_state'],'UNKNOWN')
                    self.assertFalse(result['removal_available'])
                    with self.assertRaises(SnapshotError): recovery.remove_snapshot(identifier,True)
                    self.assertTrue(all(args[0]=='pool.snapshot.query' for args,kwargs in call.call_args_list))
                with store.transaction() as operation:
                    self.assertEqual(operation.snapshot_id,identifier)
                    self.assertEqual(operation.phase,Phase.RECOVERY_REQUIRED)
                self.assertIn(identifier,api.present)

    def test_lost_delete_reply_requires_fresh_confirmation_of_absence(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            store,api,recovery,identifier=self.setup_recovery(directory)
            original=api.call
            def lost_reply(method,*args):
                result=original(method,*args)
                if method=='pool.snapshot.delete': raise TimeoutError('secret transport detail')
                return result
            with patch.object(api,'call',side_effect=lost_reply):
                with self.assertRaises(TimeoutError): recovery.remove_snapshot(identifier,True)
            self.assertNotIn(identifier,api.present)
            with store.transaction() as operation: self.assertEqual(operation.snapshot_id,identifier)
            result=recovery.inspect()
            self.assertEqual(result['snapshot_state'],'ABSENT')
            self.assertTrue(result['removal_available'])
            with self.assertRaises(OperationDenied): recovery.remove_snapshot(identifier)
            api.calls.clear()
            recovery.remove_snapshot(identifier,True)
            self.assertFalse(any(method=='pool.snapshot.delete' for method,args in api.calls))
            with store.transaction() as operation:
                self.assertIsNone(operation.snapshot_id)
                self.assertEqual(operation.phase,Phase.RECOVERY_REQUIRED)
            self.assertEqual(recovery.inspect()['snapshot_state'],'NONE')

    def test_failed_post_delete_verification_keeps_intent_until_absence_is_confirmed(self):
        from unittest.mock import patch
        from plexconfigcontrol.snapshots import SnapshotError
        with tempfile.TemporaryDirectory() as directory:
            store,api,recovery,identifier=self.setup_recovery(directory)
            original=api.call
            def broken_query(method,*args):
                if method=='pool.snapshot.query' and not api.present: return None
                return original(method,*args)
            with patch.object(api,'call',side_effect=broken_query):
                with self.assertRaises(SnapshotError): recovery.remove_snapshot(identifier,True)
                self.assertEqual(recovery.inspect()['snapshot_state'],'UNKNOWN')
            with store.transaction() as operation: self.assertEqual(operation.snapshot_id,identifier)
            self.assertEqual(recovery.inspect()['snapshot_state'],'ABSENT')
            recovery.remove_snapshot(identifier,True)
            with store.transaction() as operation: self.assertIsNone(operation.snapshot_id)

    def test_inspection_hides_transport_errors_and_cannot_contend_with_active_work(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            store,api,recovery,identifier=self.setup_recovery(directory)
            with patch.object(api,'call',side_effect=TimeoutError('API-key=secret')):
                result=recovery.inspect()
            self.assertNotIn('secret',str(result))
            self.assertFalse(result['removal_available'])
            with operation_lock(directory):
                with self.assertRaises(OperationBusy): recovery.inspect()
            with store.transaction() as operation: operation.phase=Phase.RUNNING
            api.calls.clear()
            self.assertEqual(recovery.inspect()['snapshot_state'],'NOT_CHECKED')
            self.assertEqual(api.calls,[])

    def test_restore_snapshot_removal_explicitly_warns_about_loss_of_recovery_point(self):
        with tempfile.TemporaryDirectory() as directory:
            store=StateStore(directory);api=API();history=History(directory)
            with store.transaction() as operation:
                operation.begin('RESTORE');operation.archive_validated('digest')
                operation.observe_plex('STOPPED');operation.confirm_restore('RESTORE','STOPPED','digest')
            identifier=Snapshots(api,store,'test/config').create()
            with store.transaction() as operation: operation.finish(False)
            recovery=Recovery(api,store,history,directory,'test/config')
            result=recovery.inspect()
            self.assertTrue(result['loses_restore_recovery_point'])
            self.assertTrue(result['removal_available'])
            self.assertIn(identifier,api.present)
