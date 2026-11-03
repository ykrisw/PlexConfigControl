import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
from plexconfigcontrol.eventlog import EventLog

STAMP = datetime(2026,11,3,4,15,35,tzinfo=timezone.utc)

class LogTests(unittest.TestCase):
    def test_naming_finalize_and_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            log=EventLog(directory,'Backup',STAMP)
            log.write('Archive verified', at=STAMP)
            content=log.finish()
            path=Path(directory)/'Backup_2026.11.03_04.15.35.log'
            self.assertEqual(path.read_text(),content)
            with self.assertRaises(FileExistsError): EventLog(directory,'Backup',STAMP)
            with self.assertRaises(ValueError): log.write('changed')
            self.assertEqual(path.read_text(),content)
            self.assertEqual(len(list(Path(directory).iterdir())),1)

    def test_missing_directory_is_not_created_elsewhere(self):
        with tempfile.TemporaryDirectory() as directory:
            missing=Path(directory)/'Logs'
            with self.assertRaises(FileNotFoundError): EventLog(missing,'Restore',STAMP)
            self.assertFalse(missing.exists())

    def test_symlink_directory_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'real').mkdir()
            (root/'Logs').symlink_to(root/'real',target_is_directory=True)
            with self.assertRaises(OSError): EventLog(root/'Logs','Backup',STAMP)
            self.assertEqual(list((root/'real').iterdir()),[])

    def test_directory_entry_must_be_durable_before_using_log(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('plexconfigcontrol.eventlog.os.fsync', side_effect=OSError('disk')):
                with self.assertRaises(OSError): EventLog(directory, 'Recovery', STAMP)
            # The failed log is never silently overwritten on retry.
            with self.assertRaises(FileExistsError): EventLog(directory, 'Recovery', STAMP)
