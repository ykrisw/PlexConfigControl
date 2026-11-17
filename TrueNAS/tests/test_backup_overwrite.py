"""Replacement safety with real archives and a fake, dataset-scoped host API."""
import hashlib
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from plexconfigcontrol import publication_intent as intent
from plexconfigcontrol.archive_store import ArchiveChanged, ArchiveStore
from plexconfigcontrol.archives import REQUIRED
from plexconfigcontrol.backup import Backup, ArchiveNameCollision
from plexconfigcontrol.backup_archive import create_archive
from plexconfigcontrol.history import History
from plexconfigcontrol.operations import Phase
from plexconfigcontrol.progress import Progress
from plexconfigcontrol.publish import PublishError, retire_original
from plexconfigcontrol.startup import reconcile_startup
from plexconfigcontrol.state import StateStore
from test_snapshots import API

OLD = 'TrueNASPlexConfig_2020.01.01_00.00.00.tar.gz'
NEW = 'TrueNASPlexConfig_2026.11.03_12.00.00.tar.gz'
STAGE = '.pcc-'+'a'*32+'.tmp'


class ReplacementTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state, destination, source = root/'state', root/'Plex Config', root/'snapshot'
            (destination/'Logs').mkdir(parents=True)
            source.mkdir()
            for name in REQUIRED:
                file = source/name.removeprefix('config/')
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b'fixture contents')
            old = destination/OLD
            old.write_bytes(b'original archive must survive failures')
            @contextmanager
            def reader(identifier):
                self.assertIn(identifier, api.present)
                yield source
            api, store = API(), StateStore(state)
            history, progress = History(state), Progress(state)
            backup = Backup(api, store, history, progress, state, destination,
                            'test/config', reader)
            selected = ArchiveStore(destination, state).list()[0]
            with patch('plexconfigcontrol.backup.archive_name', return_value=NEW):
                yield backup, selected, old, api, store, history, progress

    def phase(self, store):
        with store.transaction() as operation:
            return operation.phase

    def test_success_retires_only_after_snapshot_absence_and_new_verification(self):
        with self.fixture() as (backup, selected, old, api, store, history, progress):
            def retire(*args):
                self.assertEqual(api.present, set())
                self.assertEqual(progress.read()['stage'], 'VERIFYING_ARCHIVE')
                self.assertTrue(old.exists())
                self.assertTrue((backup.destination/NEW).exists())
                self.assertTrue(intent.pending(backup.state))
                record = intent.read_replacement(backup.state)
                self.assertEqual(record['original'], OLD)
                self.assertEqual(record['archive'], NEW)
                self.assertEqual(record['sha256'], hashlib.sha256(
                    (backup.destination/NEW).read_bytes()).hexdigest())
                retire_original(*args)
            with patch('plexconfigcontrol.backup.retire_original', side_effect=retire):
                self.assertEqual(backup.run_overwrite(selected), NEW)
            self.assertFalse(old.exists())
            self.assertEqual([a.name for a in ArchiveStore(backup.destination, backup.state).list()], [NEW])
            self.assertFalse(intent.pending(backup.state))
            self.assertEqual(self.phase(store), Phase.SUCCESS)
            self.assertEqual(progress.read()['stage'], 'COMPLETED')
            self.assertEqual(history.list()[0]['status'], 'SUCCESS')
            self.assertFalse(any(method in ('app.start', 'app.stop') for method, _ in api.calls))
            self.assertEqual(len(list((backup.destination/'Logs').iterdir())), 1)

    def test_missing_confirmation_or_stale_selection_makes_no_host_calls(self):
        with self.fixture() as (backup, selected, old, api, *_):
            with self.assertRaises(ValueError):
                backup.run_overwrite(None)
            old.write_bytes(b'replaced outside panel')
            with self.assertRaises(ArchiveChanged):
                backup.run_overwrite(selected)
            self.assertEqual(api.calls, [])
            self.assertEqual(list((backup.destination/'Logs').iterdir()), [])

    def test_second_archive_invalidates_overwrite_confirmation(self):
        with self.fixture() as (backup, selected, old, api, *_):
            (backup.destination/NEW).write_bytes(b'another archive')
            with self.assertRaises(ArchiveChanged):
                backup.run_overwrite(selected)
            self.assertTrue(old.exists())
            self.assertEqual(api.calls, [])

    def test_same_dated_name_never_silently_overwrites(self):
        with self.fixture() as (backup, selected, old, api, *_):
            with patch('plexconfigcontrol.backup.archive_name', return_value=OLD):
                with self.assertRaises(ArchiveNameCollision):
                    backup.run_overwrite(selected)
            self.assertEqual(api.calls, [])
            self.assertTrue(old.exists())

    def test_archive_failure_preserves_original_and_cleans_snapshot(self):
        with self.fixture() as (backup, selected, old, api, store, history, progress):
            original = old.read_bytes()
            with patch('plexconfigcontrol.backup.create_archive', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    backup.run_overwrite(selected)
            self.assertEqual(old.read_bytes(), original)
            self.assertEqual(api.present, set())
            self.assertEqual(self.phase(store), Phase.FAILED)
            self.assertFalse((backup.destination/NEW).exists())

    def test_snapshot_cleanup_failure_preserves_original_and_prevents_publication(self):
        with self.fixture() as (backup, selected, old, api, store, *_):
            api.keep = True
            with self.assertRaises(Exception):
                backup.run_overwrite(selected)
            self.assertTrue(old.exists())
            self.assertFalse((backup.destination/NEW).exists())
            self.assertEqual(self.phase(store), Phase.RECOVERY_REQUIRED)
            self.assertTrue(api.present)
            self.assertFalse(intent.pending(backup.state))

    def test_external_change_even_with_restored_mtime_keeps_both_archives(self):
        with self.fixture() as (backup, selected, old, api, store, *_):
            original_stat = old.stat()
            def build(*args, **kwargs):
                # Keep length/mtime unchanged; ctime must still invalidate selection.
                old.write_bytes(b'X'*selected.size)
                os.utime(old, ns=(original_stat.st_atime_ns, selected.modified_ns))
                return create_archive(*args, **kwargs)
            with patch('plexconfigcontrol.backup.create_archive', side_effect=build):
                with self.assertRaises(ArchiveChanged):
                    backup.run_overwrite(selected)
            self.assertEqual(old.read_bytes(), b'X'*selected.size)
            self.assertTrue((backup.destination/NEW).exists())
            self.assertEqual(api.present, set())
            self.assertEqual(self.phase(store), Phase.RECOVERY_REQUIRED)
            self.assertEqual(intent.describe(backup.state)['replaced_archive'], OLD)
            with self.assertRaises(RuntimeError):
                backup.run_new()

    def test_corrupted_published_copy_never_removes_original(self):
        with self.fixture() as (backup, selected, old, api, store, *_):
            original = old.read_bytes()
            def corrupt(*args):
                (backup.destination/NEW).write_bytes(b'corrupted after publication')
                retire_original(*args)
            with patch('plexconfigcontrol.backup.retire_original', side_effect=corrupt):
                with self.assertRaises(PublishError):
                    backup.run_overwrite(selected)
            self.assertEqual(old.read_bytes(), original)
            self.assertTrue(intent.pending(backup.state))
            self.assertEqual(self.phase(store), Phase.RECOVERY_REQUIRED)

    def test_failed_retirement_retains_marker_and_restart_does_not_delete_files(self):
        with self.fixture() as (backup, selected, old, api, store, history, progress):
            with patch('plexconfigcontrol.backup.retire_original', side_effect=PermissionError('access denied')):
                with self.assertRaises(PermissionError):
                    backup.run_overwrite(selected)
            before = {file.name: file.read_bytes() for file in backup.destination.glob('*.tar.gz')}
            reconcile_startup(store, progress, history, backup.state)
            self.assertEqual({file.name: file.read_bytes() for file in backup.destination.glob('*.tar.gz')}, before)
            self.assertTrue(old.exists())
            self.assertTrue(intent.pending(backup.state))
            self.assertEqual(self.phase(store), Phase.RECOVERY_REQUIRED)

    def test_interruption_after_publication_preserves_both_and_blocks_after_restart(self):
        with self.fixture() as (backup, selected, old, api, store, history, progress):
            with patch('plexconfigcontrol.backup.retire_original', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    backup.run_overwrite(selected)
            self.assertTrue(old.exists())
            self.assertTrue((backup.destination/NEW).exists())
            self.assertEqual(api.present, set())
            self.assertEqual(self.phase(store), Phase.RUNNING)
            result = reconcile_startup(store, progress, history, backup.state)
            self.assertTrue(result['interrupted'])
            self.assertEqual(self.phase(store), Phase.RECOVERY_REQUIRED)
            self.assertTrue(intent.pending(backup.state))
            self.assertFalse(any(event['status'] == 'SUCCESS' for event in history.list()))
            with self.assertRaises(RuntimeError):
                backup.run_overwrite(selected)

    def test_filename_created_externally_during_backup_is_never_overwritten(self):
        with self.fixture() as (backup, selected, old, api, store, *_):
            def build(*args, **kwargs):
                (backup.destination/NEW).write_bytes(b'externally created archive')
                return create_archive(*args, **kwargs)
            with patch('plexconfigcontrol.backup.create_archive', side_effect=build):
                with self.assertRaises(FileExistsError):
                    backup.run_overwrite(selected)
            self.assertTrue(old.exists())
            self.assertEqual((backup.destination/NEW).read_bytes(), b'externally created archive')
            self.assertEqual(api.present, set())
            self.assertEqual(self.phase(store), Phase.RECOVERY_REQUIRED)
            self.assertTrue(intent.pending(backup.state))
            self.assertEqual(list(backup.destination.glob('.pcc-*.tmp')), [])

    def test_marker_clear_failure_reports_recovery_after_verified_replacement(self):
        with self.fixture() as (backup, selected, old, api, store, history, progress):
            with patch('plexconfigcontrol.backup.publication_intent.clear_replacement', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    backup.run_overwrite(selected)
            self.assertFalse(old.exists())
            self.assertTrue((backup.destination/NEW).exists())
            self.assertTrue(intent.pending(backup.state))
            self.assertEqual(self.phase(store), Phase.RECOVERY_REQUIRED)
            self.assertEqual(history.list()[0]['status'], 'FAILED')
            self.assertEqual(progress.read()['stage'], 'CLEANUP_REQUIRED')


class ReplacementRecordTests(unittest.TestCase):
    def record(self, directory):
        intent.record_replacement(directory, STAGE, NEW, 'a'*64, OLD,
                                  dict(device=1, inode=2, size=3, modified_ns=4, changed_ns=5))

    def test_record_is_private_exclusive_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            self.record(directory)
            marker = Path(directory)/intent.REPLACEMENT_MARKER
            before = marker.read_bytes()
            self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
            self.assertEqual(intent.read_replacement(directory)['original'], OLD)
            with self.assertRaises(FileExistsError):
                self.record(directory)
            self.assertEqual(marker.read_bytes(), before)
            store, progress, history = StateStore(directory), Progress(directory), History(directory)
            reconcile_startup(store, progress, history, directory)
            with store.transaction() as operation:
                self.assertEqual(operation.phase, Phase.RECOVERY_REQUIRED)
            intent.clear_replacement(directory)
            self.assertFalse(intent.pending(directory))

    def test_corrupt_oversized_symlink_and_conflicting_records_remain_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory)/intent.REPLACEMENT_MARKER
            for payload in (b'{}', b'\xff', b'x'*2049, b'[]'):
                marker.write_bytes(payload)
                self.assertTrue(intent.pending(directory))
                self.assertEqual(intent.describe(directory)['status'], 'RECORD_UNREADABLE')
            marker.unlink()
            marker.symlink_to(Path(directory)/'missing')
            self.assertEqual(intent.describe(directory)['status'], 'RECORD_UNREADABLE')
            marker.unlink()
            self.record(directory)
            intent.record(directory, STAGE, NEW)
            self.assertEqual(intent.describe(directory)['status'], 'RECORD_UNREADABLE')
