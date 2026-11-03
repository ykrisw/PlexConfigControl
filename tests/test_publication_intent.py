import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from plexconfigcontrol import publication_intent as intent
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.progress import Progress
from plexconfigcontrol.history import History
from plexconfigcontrol.operations import Phase
from plexconfigcontrol.startup import reconcile_startup

STAGE = '.pcc-' + 'a'*32 + '.tmp'
ARCHIVE = 'TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'

class PublicationIntentTests(unittest.TestCase):
    def test_record_is_exclusive_private_and_clear_is_durable(self):
        with tempfile.TemporaryDirectory() as d:
            intent.record(d,STAGE,ARCHIVE)
            marker=Path(d)/intent.MARKER
            original=marker.read_bytes()
            self.assertEqual(marker.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError): intent.record(d,STAGE,ARCHIVE)
            self.assertEqual(marker.read_bytes(),original)
            with patch.object(intent.os,'fsync',wraps=intent.os.fsync) as sync:
                intent.clear(d)
                self.assertEqual(sync.call_count,1)
            self.assertFalse(intent.pending(d))

    def test_failed_durability_keeps_record_and_startup_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            store=StateStore(d); progress=Progress(d); history=History(d)
            with patch.object(intent.os,'fsync',side_effect=OSError('disk error')):
                with self.assertRaises(OSError): intent.record(d,STAGE,ARCHIVE)
            self.assertTrue(intent.pending(d))
            result=reconcile_startup(store,progress,history,d)
            self.assertTrue(result['interrupted'])
            self.assertEqual(result['phase'],Phase.RECOVERY_REQUIRED.value)
            reconcile_startup(store,progress,history,d)
            self.assertEqual(len(history.list()),1)

    def test_invalid_identity_creates_nothing_and_symlink_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): intent.record(d,'../outside',ARCHIVE)
            self.assertEqual(list(Path(d).iterdir()),[])
            (Path(d)/intent.MARKER).symlink_to(Path(d)/'missing')
            self.assertTrue(intent.pending(d))
            with self.assertRaises(FileExistsError): intent.record(d,STAGE,ARCHIVE)
