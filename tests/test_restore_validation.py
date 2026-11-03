import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.archives import REQUIRED, InvalidArchive, validate_archive
from plexconfigcontrol.history import History
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.operations import Phase
from plexconfigcontrol.restore_validation import RestoreValidation
from plexconfigcontrol.progress import Progress

NAME='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'
class RestoreValidationTests(unittest.TestCase):
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
            service.cancel()
            self.assertEqual(Progress(state).read()['stage'],'CANCELLED')
            self.assertFalse(Progress(state).read()['active'])
            with store.transaction() as operation: self.assertEqual(operation.phase,Phase.IDLE)
    def test_invalid_archive_leaves_no_active_validation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); backup=root/'backup'; backup.mkdir(); (backup/NAME).write_bytes(b'broken')
            store=StateStore(root/'state'); history=History(root/'state')
            service=RestoreValidation(backup,root/'state',store,history)
            with self.assertRaises(InvalidArchive): service.validate(NAME)
            self.assertEqual(Progress(root/'state').read()['stage'],'FAILED')
            with store.transaction() as operation: self.assertEqual(operation.phase,Phase.FAILED)
