import json
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plexconfigcontrol.archive_discovery import ArchiveDiscovery
from plexconfigcontrol.history import History
from plexconfigcontrol.operations import Phase
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.web import Web
from plexconfigcontrol.publication_intent import record

NAME='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'


class DiscoveryTests(unittest.TestCase):
    def setup_case(self, root, *, logs=True, enabled=True):
        destination, state = root/'Plex Config', root/'state'
        destination.mkdir()
        if logs:
            (destination/'Logs').mkdir()
        history = History(state)
        return destination, state, history, ArchiveDiscovery(destination, state, history, permanent_logs=enabled)

    def test_arrival_creates_one_info_event_and_one_permanent_log_across_restarts(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination, state, history, discovery = self.setup_case(Path(temporary))
            self.assertEqual(discovery.scan(), [])
            (destination/NAME).write_bytes(b'not validated, possibly still being copied')
            self.assertEqual([item.name for item in discovery.scan()], [NAME])
            event = history.list()[0]
            self.assertEqual(event['kind'], 'ARCHIVE_DETECTED')
            self.assertEqual(event['status'], 'INFO')
            self.assertEqual(event['archive'], NAME)
            detail = history.detail(event['id'])
            self.assertIn('NOT VALIDATED', detail['log'])
            self.assertIn('original copy time and source are unknown', detail['log'])
            logs = list((destination/'Logs').glob('ArchiveImport_*.log'))
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].read_text(), detail['log'])
            self.assertEqual(discovery.status()['pending_logs'], 0)
            for _ in range(3):
                ArchiveDiscovery(destination, state, History(state)).scan()
            self.assertEqual(len(history.list()), 1)
            self.assertEqual(list((destination/'Logs').iterdir()), logs)

    def test_history_clear_neither_deletes_log_nor_recreates_cleared_event(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination, state, history, discovery = self.setup_case(Path(temporary))
            (destination/NAME).write_bytes(b'archive')
            discovery.scan()
            permanent = next((destination/'Logs').iterdir())
            contents = permanent.read_bytes()
            history.clear([history.list()[0]['id']])
            ArchiveDiscovery(destination, state, History(state)).scan()
            self.assertEqual(history.list(), [])
            self.assertEqual(permanent.read_bytes(), contents)
            # User manually removing a completed log must not make it reappear.
            permanent.unlink()
            discovery.scan()
            self.assertEqual(list((destination/'Logs').iterdir()), [])
            self.assertEqual(history.list(), [])

    def test_observed_removal_and_return_creates_another_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination, state, history, discovery = self.setup_case(Path(temporary))
            archive = destination/NAME
            archive.write_bytes(b'archive')
            discovery.scan()
            external = Path(temporary)/'external.tar.gz'
            shutil.copyfile(archive, external)
            archive.unlink()
            discovery.scan()
            shutil.copyfile(external, archive)
            discovery.scan()
            self.assertEqual(len(history.list()), 2)
            self.assertEqual(len(list((destination/'Logs').iterdir())), 2)

    def test_partial_inplace_copy_does_not_spam_an_import_per_chunk(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination, state, history, discovery = self.setup_case(Path(temporary))
            archive = destination/NAME
            archive.write_bytes(b'part')
            discovery.scan()
            with archive.open('ab') as stream:
                stream.write(b'more bytes')
            discovery.scan()
            self.assertEqual(len(history.list()), 1)
            self.assertIn('NOT VALIDATED', history.detail(history.list()[0]['id'])['log'])

    def test_app_created_file_is_remembered_independently_of_backup_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination, state, history, discovery = self.setup_case(Path(temporary))
            (destination/NAME).write_bytes(b'app published archive')
            discovery.remember_created(NAME)
            event = history.add('BACKUP', 'SUCCESS', 'Backup completed', NAME)
            history.clear([event])
            ArchiveDiscovery(destination, state, History(state)).scan()
            self.assertEqual(history.list(), [])
            self.assertEqual(list((destination/'Logs').iterdir()), [])

    def test_readonly_mount_queues_permanent_log_without_writing_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination, state, history, discovery = self.setup_case(Path(temporary), enabled=False)
            archive = destination/NAME
            archive.write_bytes(b'archive')
            before = archive.stat()
            with patch.object(discovery, '_flush_logs', side_effect=AssertionError('Must not write archive mount')):
                discovery.scan()
            self.assertEqual(archive.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertEqual(list((destination/'Logs').iterdir()), [])
            self.assertEqual(discovery.status(), {'pending_logs': 1, 'permanent_logs_enabled': False})
            history.clear([history.list()[0]['id']])
            # A future writable deployment flushes the operational log only;
            # explicitly deleted web history must remain deleted.
            writable = ArchiveDiscovery(destination, state, history)
            writable.scan()
            self.assertEqual(writable.status()['pending_logs'], 0)
            self.assertEqual(len(list((destination/'Logs').iterdir())), 1)
            self.assertEqual(history.list(), [])

    def test_missing_logs_or_symlink_does_not_redirect_or_discard_pending_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination, state, history, discovery = self.setup_case(root, logs=False)
            outside = root/'outside'
            outside.mkdir()
            (destination/'Logs').symlink_to(outside, target_is_directory=True)
            (destination/NAME).write_bytes(b'archive')
            discovery.scan()
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual(discovery.status()['pending_logs'], 1)
            (destination/'Logs').unlink()
            (destination/'Logs').mkdir()
            discovery.scan()
            self.assertEqual(discovery.status()['pending_logs'], 0)
            self.assertEqual(len(history.list()), 1)

    def test_failed_ack_reconciles_complete_log_without_editing_or_duplicating(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination, state, history, discovery = self.setup_case(Path(temporary), logs=False)
            (destination/NAME).write_bytes(b'archive')
            discovery.scan()
            with history.connect() as db:
                name, body = db.execute('SELECT name,body FROM archive_log_outbox').fetchone()
            (destination/'Logs').mkdir()
            permanent = destination/'Logs'/name
            permanent.write_text(body)  # Simulate crash after write, before ack.
            before = permanent.stat()
            discovery.scan()
            self.assertEqual(discovery.status()['pending_logs'], 0)
            self.assertEqual(permanent.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertEqual(len(history.list()), 1)

    def test_conflicting_permanent_log_is_never_overwritten_or_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination, state, history, discovery = self.setup_case(Path(temporary), logs=False)
            (destination/NAME).write_bytes(b'archive')
            discovery.scan()
            with history.connect() as db:
                name = db.execute('SELECT name FROM archive_log_outbox').fetchone()[0]
            (destination/'Logs').mkdir()
            permanent = destination/'Logs'/name
            permanent.write_bytes(b'conflicting or partial log')
            discovery.scan()
            self.assertEqual(permanent.read_bytes(), b'conflicting or partial log')
            self.assertEqual(discovery.status()['pending_logs'], 1)
            self.assertEqual(len(history.list()), 1)

    def test_pending_publication_and_active_backup_are_not_misclassified_as_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination, state, history, discovery = self.setup_case(Path(temporary))
            (destination/NAME).write_bytes(b'new app archive')
            store = StateStore(state)
            with store.transaction() as operation:
                operation.begin('BACKUP')
                operation.begin_backup()
            self.assertEqual(len(discovery.scan()), 1)
            self.assertEqual(history.list(), [])
            with store.transaction() as operation:
                operation.phase = Phase.FAILED
            record(state, '.pcc-'+'a'*32+'.tmp', NAME)
            discovery.scan()
            self.assertEqual(history.list(), [])

    def test_history_endpoint_discovers_files_even_without_visiting_backup_or_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root/'Plex Config'
            (destination/'Logs').mkdir(parents=True)
            (destination/NAME).write_bytes(b'external archive')
            app = Web(root/'state', destination)
            token, _ = app.sessions.create()
            responses = []
            body = b''.join(app({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/api/history',
                'HTTP_COOKIE': 'pcc_session='+token, 'wsgi.input': io.BytesIO()},
                lambda status, headers: responses.append(status)))
            self.assertEqual(responses, ['200 OK'])
            events = json.loads(body)
            self.assertEqual(events[0]['kind'], 'ARCHIVE_DETECTED')
            self.assertEqual(events[0]['archive'], NAME)
            self.assertEqual(len(list((destination/'Logs').iterdir())), 1)
