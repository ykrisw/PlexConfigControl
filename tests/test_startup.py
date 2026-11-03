import tempfile
import unittest
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.progress import Progress
from plexconfigcontrol.history import History
from plexconfigcontrol.operations import Phase, OperationDenied
from plexconfigcontrol.startup import reconcile_startup
from plexconfigcontrol.locking import operation_lock, OperationBusy

class StartupTests(unittest.TestCase):
    def test_restart_reports_interrupted_validation_and_preserves_archive_name(self):
        with tempfile.TemporaryDirectory() as d:
            store=StateStore(d); progress=Progress(d); history=History(d)
            with store.transaction() as op:
                op.begin('RESTORE')
                op.validation_details={'archive':'selected.tar.gz','status':'VALIDATING','reason':None}
            progress.start('RESTORE')
            reconcile_startup(store,progress,history,d)
            with StateStore(d).transaction() as op:
                self.assertEqual(op.validation_details['status'],'INTERRUPTED')
                self.assertEqual(op.validation_details['archive'],'selected.tar.gz')
                self.assertIsNone(op.archive_identity)

    def test_interrupted_backup_preserves_snapshot_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            store=StateStore(d); progress=Progress(d); history=History(d)
            with store.transaction() as op:
                op.begin('BACKUP'); op.begin_backup(); op.record_snapshot_intent('test/config','pcc-backup-test')
            progress.start('BACKUP'); progress.update('CREATING_ARCHIVE',done=12)
            result=reconcile_startup(store,progress,history,d)
            self.assertTrue(result['interrupted'])
            self.assertEqual(result['snapshot_id'],'test/config@pcc-backup-test')
            self.assertEqual(progress.read()['stage'],'CLEANUP_REQUIRED')
            reconcile_startup(store,progress,history,d)
            self.assertEqual(len(history.list()),1)
            with store.transaction() as op:
                with self.assertRaises(OperationDenied): op.begin('BACKUP')

    def test_live_operation_is_not_reclassified(self):
        with tempfile.TemporaryDirectory() as d:
            store=StateStore(d); progress=Progress(d); history=History(d)
            with store.transaction() as op: op.begin('BACKUP')
            with operation_lock(d):
                with self.assertRaises(OperationBusy): reconcile_startup(store,progress,history,d)
            with store.transaction() as op: self.assertEqual(op.phase,Phase.VALIDATING)

    def test_waiting_for_manual_stop_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            store=StateStore(d); progress=Progress(d); history=History(d)
            with store.transaction() as op:
                op.begin('RESTORE'); op.archive_validated('verified-digest')
            result=reconcile_startup(store,progress,history,d)
            self.assertFalse(result['interrupted'])
            self.assertEqual(result['phase'],'WAITING_FOR_PLEX_STOP')
