import tempfile
import sqlite3
import unittest
from pathlib import Path
from plexconfigcontrol.history import History


class HistoryTests(unittest.TestCase):
    def test_deleted_identities_are_not_reused_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            history=History(directory)
            old=history.add('BACKUP','SUCCESS','old')
            history.clear([old])
            history=History(directory)
            new=history.add('RESTORE','SUCCESS','new')
            self.assertGreater(new,old)
            history.clear([old])
            self.assertEqual(history.detail(new)['log'],'new')

    def test_legacy_identity_migration_preserves_events_and_log_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            with sqlite3.connect(Path(directory)/'history.sqlite3') as db:
                db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, created TEXT NOT NULL, '
                           'kind TEXT NOT NULL,status TEXT NOT NULL,archive TEXT,log TEXT NOT NULL)')
                db.execute("INSERT INTO events VALUES(42,'2026-11-03','BACKUP','SUCCESS','archive','unchanged')")
            history=History(directory)
            self.assertEqual(history.detail(42)['log'],'unchanged')
            history.clear([42])
            self.assertGreater(history.add('RESTORE','SUCCESS','new'),42)
            History(directory)  # Repeated initialization must not migrate again.

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
