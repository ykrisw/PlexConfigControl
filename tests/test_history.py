import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.history import History


class HistoryTests(unittest.TestCase):
    def test_delete_selected_keeps_logs_and_other_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / 'Plex Config' / 'Logs'
            logs.mkdir(parents=True)
            permanent = logs / 'Backup_2026.11.03_04.15.35.log'
            permanent.write_text('permanent operation log')
            history = History(root / 'ixVolume')
            first = history.add('BACKUP', 'SUCCESS', 'full first log')
            second = history.add('RESTORE', 'FAILED', 'full second log')
            history.clear([first])
            reopened = History(root / 'ixVolume')
            self.assertIsNone(reopened.detail(first))
            self.assertEqual(reopened.detail(second)['log'], 'full second log')
            self.assertEqual(permanent.read_text(), 'permanent operation log')

    def test_list_hides_full_log_and_orders_newest_first(self):
        with tempfile.TemporaryDirectory() as directory:
            history = History(directory)
            history.add('BACKUP', 'SUCCESS', 'one')
            latest = history.add('RESTORE', 'FAILED', 'two')
            rows = history.list()
            self.assertEqual(rows[0]['id'], latest)
            self.assertNotIn('log', rows[0])
