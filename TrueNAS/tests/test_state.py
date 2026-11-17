import tempfile
import unittest

from plexconfigcontrol.operations import OperationDenied, Phase
from plexconfigcontrol.state import StateStore


class StateTests(unittest.TestCase):
    def test_restart_retains_snapshot_and_blocks_new_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            with store.transaction() as operation:
                operation.begin('BACKUP')
                operation.begin_backup()
                operation.record_snapshot_intent('test/config', 'pcc-backup-test')
            reopened = StateStore(directory)
            with self.assertRaises(OperationDenied):
                with reopened.transaction() as operation:
                    operation.begin('BACKUP')
            with reopened.transaction() as operation:
                self.assertEqual(operation.snapshot_id, 'test/config@pcc-backup-test')
                operation.finish(True)
                self.assertEqual(operation.phase, Phase.RECOVERY_REQUIRED)

    def test_failed_transaction_preserves_previous_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            with self.assertRaises(RuntimeError):
                with store.transaction() as operation:
                    operation.begin('RESTORE')
                    raise RuntimeError('simulated failure')
            with store.transaction() as operation:
                self.assertEqual(operation.phase, Phase.IDLE)

    def test_wrong_snapshot_cannot_be_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            with store.transaction() as operation:
                operation.begin('BACKUP')
                operation.begin_backup()
                operation.record_snapshot_intent('test/config', 'pcc-backup-test')
            with self.assertRaises(OperationDenied):
                with store.transaction() as operation:
                    operation.confirm_snapshot_absent('other/config@pcc-backup-test')
            with store.transaction() as operation:
                self.assertIsNotNone(operation.snapshot_id)


if __name__ == '__main__':
    unittest.main()
