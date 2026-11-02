import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.archives import REQUIRED, InvalidArchive
from plexconfigcontrol.history import History
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.operations import Phase
from plexconfigcontrol.restore_validation import RestoreValidation

NAME='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'
class RestoreValidationTests(unittest.TestCase):
    def test_validate_wait_and_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); backup=root/'backup'; backup.mkdir(); state=root/'state'
            with tarfile.open(backup/NAME,'w:gz') as archive:
                for name in REQUIRED:
                    member=tarfile.TarInfo(name); member.size=4
                    archive.addfile(member,io.BytesIO(b'test'))
            store=StateStore(state); history=History(state)
            service=RestoreValidation(backup,state,store,history)
            result=service.validate(NAME)
            with store.transaction() as operation:
                self.assertEqual(operation.phase,Phase.WAITING_FOR_PLEX_STOP)
                self.assertEqual(operation.archive_identity,result['sha256'])
                self.assertIsNone(operation.snapshot_id)
            service.cancel()
            with store.transaction() as operation: self.assertEqual(operation.phase,Phase.IDLE)
    def test_invalid_archive_leaves_no_active_validation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); backup=root/'backup'; backup.mkdir(); (backup/NAME).write_bytes(b'broken')
            store=StateStore(root/'state'); history=History(root/'state')
            service=RestoreValidation(backup,root/'state',store,history)
            with self.assertRaises(InvalidArchive): service.validate(NAME)
            with store.transaction() as operation: self.assertEqual(operation.phase,Phase.FAILED)
