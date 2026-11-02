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
