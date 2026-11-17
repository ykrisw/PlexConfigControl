import tempfile
import unittest
from plexconfigcontrol.progress import Progress

class ProgressTests(unittest.TestCase):
    def test_unknown_total_has_no_percent_and_restart_preserves_stage(self):
        with tempfile.TemporaryDirectory() as d:
            p=Progress(d); p.start('BACKUP',now=100)
            p.update('CREATING_ARCHIVE',done=200,now=110)
            result=Progress(d).read(now=120)
            self.assertIsNone(result['stage_percent']); self.assertEqual(result['elapsed_seconds'],20)
            p.update('CREATING_ARCHIVE',done=500,total=1000,now=121)
            self.assertEqual(p.read(now=122)['stage_percent'],50)
            with self.assertRaises(ValueError): p.update('CREATING_ARCHIVE',done=499,total=1000)
    def test_terminal_elapsed_stops_and_stage_change_resets_counter(self):
        with tempfile.TemporaryDirectory() as d:
            p=Progress(d); p.start('RESTORE',now=100)
            p.update('RESTORING',done=100,total=100,now=110)
            p.update('VERIFYING_RESTORE',done=0,now=111)
            p.update('FAILED',now=115)
            self.assertEqual(p.read(now=999)['elapsed_seconds'],15)
            self.assertFalse(p.read()['active'])
            with self.assertRaises(ValueError): p.update('COMPLETED')

    def test_fail_closed_can_replace_premature_success_without_changing_elapsed(self):
        with tempfile.TemporaryDirectory() as directory:
            progress=Progress(directory);progress.start('RESTORE',now=100)
            progress.update('COMPLETED',done=5,total=5,now=110)
            progress.fail_closed(True,now=150)
            result=progress.read(now=999)
            self.assertEqual(result['stage'],'CLEANUP_REQUIRED')
            self.assertEqual(result['elapsed_seconds'],10)
            self.assertIsNone(result['stage_percent'])
            progress.fail_closed(False,now=160)
            self.assertEqual(progress.read()['stage'],'CLEANUP_REQUIRED')
            with self.assertRaises(ValueError):progress.fail_closed(1)
