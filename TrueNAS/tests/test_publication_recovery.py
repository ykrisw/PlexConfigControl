"""Recovery uses real archive validation; no TrueNAS API or shell is involved."""
import hashlib
import io
import os
import tarfile
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from plexconfigcontrol import publication_intent as intent
from plexconfigcontrol.archive_store import ArchiveStore, file_identity
from plexconfigcontrol.archives import REQUIRED
from plexconfigcontrol.history import History
from plexconfigcontrol.locking import OperationBusy, operation_lock
from plexconfigcontrol.operations import OperationDenied, Phase
from plexconfigcontrol.progress import Progress
from plexconfigcontrol.publication_recovery import PublicationRecovery
from plexconfigcontrol.startup import reconcile_startup
from plexconfigcontrol.state import StateStore

NEW = 'TrueNASPlexConfig_2026.11.03_12.00.00.tar.gz'
OLD = 'TrueNASPlexConfig_2020.01.01_00.00.00.tar.gz'
STAGE = '.pcc-' + 'a' * 32 + '.tmp'


class PublicationRecoveryTests(unittest.TestCase):
    @contextmanager
    def fixture(self, replacement=False, legacy=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination, state = root/'Plex Config', root/'state'
            (destination/'Logs').mkdir(parents=True)
            archive = destination/NEW
            with tarfile.open(archive, 'w:gz') as output:
                for name in sorted(REQUIRED):
                    entry = tarfile.TarInfo(name)
                    entry.size = 4
                    output.addfile(entry, io.BytesIO(b'test'))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            store, progress, history = StateStore(state), Progress(state), History(state)
            with store.transaction() as operation:
                operation.kind, operation.phase = 'BACKUP', Phase.RECOVERY_REQUIRED
            progress.start('BACKUP', now=100)
            progress.update('CLEANUP_REQUIRED', now=125)
            history.add('BACKUP', 'FAILED', 'Interrupted publication', NEW)
            if replacement:
                old = destination/OLD
                old.write_bytes(b'old archive; never delete during recovery')
                intent.record_replacement(state, STAGE, NEW, digest, OLD, file_identity(old.stat()))
            else:
                intent.record(state, STAGE, NEW, None if legacy else digest)
            recovery = PublicationRecovery(store, history, progress, state, destination)
            yield recovery, archive

    def phase(self, recovery):
        with recovery.store.transaction() as operation:
            return operation.phase

    def test_inspection_changes_nothing_and_recovery_retains_old_and_failure(self):
        with self.fixture(replacement=True) as (recovery, archive):
            old = recovery.destination/OLD
            old.write_bytes(b'external edit must not be deleted')
            before = {p.name: p.read_bytes() for p in recovery.destination.iterdir() if p.is_file()}
            report = recovery.inspect()
            self.assertTrue(intent.pending(recovery.state))
            self.assertEqual(recovery.history.list()[0]['kind'], 'BACKUP')
            self.assertEqual(report['retained_older_archive'], OLD)
            self.assertEqual(report['older_archive_state'], 'CHANGED')
            result = recovery.keep_archives(report['confirmation_token'], confirmed=True)
            self.assertFalse(result['cleanup_required'])
            self.assertEqual(before, {p.name: p.read_bytes() for p in recovery.destination.iterdir() if p.is_file()})
            self.assertFalse(intent.pending(recovery.state))
            self.assertEqual(self.phase(recovery), Phase.FAILED)
            progress = recovery.progress.read(now=500)
            self.assertEqual((progress['stage'], progress['elapsed_seconds']), ('FAILED', 25))
            self.assertFalse(progress['active'])
            self.assertFalse(any(row['status'] == 'SUCCESS' for row in recovery.history.list()))
            logs = list((recovery.destination/'Logs').glob('Recovery_*.log'))
            self.assertEqual(len(logs), 1)
            permanent = logs[0].read_bytes()
            recovery.history.clear([row['id'] for row in recovery.history.list()])
            self.assertEqual(logs[0].read_bytes(), permanent)
            # Recovery remembers app origin without relying on removable history.
            from plexconfigcontrol.archive_discovery import ArchiveDiscovery
            ArchiveDiscovery(recovery.destination, recovery.state, recovery.history).scan()
            self.assertFalse(any(row.get('archive') == NEW for row in recovery.history.list()))

    def test_ordinary_digest_record_recovers(self):
        with self.fixture() as (recovery, archive):
            report = recovery.inspect()
            self.assertEqual(intent.read(recovery.state)['sha256'], report['sha256'])
            recovery.keep_archives(report['confirmation_token'], confirmed=True)
            self.assertTrue(archive.exists())
            self.assertEqual(self.phase(recovery), Phase.FAILED)

    def test_legacy_record_stays_readable_but_cannot_unlock(self):
        with self.fixture(legacy=True) as (recovery, _):
            self.assertEqual(intent.describe(recovery.state)['status'], 'VERIFICATION_REQUIRED')
            with self.assertRaises(OperationDenied): recovery.inspect()
            self.assertTrue(intent.pending(recovery.state))

    def test_wrong_digest_and_invalid_archive_stay_blocked(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), self.fixture() as (recovery, archive):
                if corrupt:
                    archive.write_bytes(b'not a gzip archive')
                else:
                    archive.write_bytes(archive.read_bytes() + b'\0' * 16)
                with self.assertRaises((ValueError, OperationDenied)): recovery.inspect()
                self.assertTrue(intent.pending(recovery.state))
                self.assertEqual(self.phase(recovery), Phase.RECOVERY_REQUIRED)

    def test_missing_or_symlink_final_is_never_followed(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink), self.fixture() as (recovery, archive):
                outside = recovery.state/'outside'
                outside.write_bytes(archive.read_bytes())
                archive.unlink()
                if symlink: archive.symlink_to(outside)
                with self.assertRaises(OSError): recovery.inspect()
                self.assertTrue(outside.exists())
                self.assertTrue(intent.pending(recovery.state))

    def test_all_remaining_stage_types_are_preserved_and_block(self):
        for kind in ('hardlink', 'file', 'directory', 'symlink'):
            with self.subTest(kind=kind), self.fixture() as (recovery, archive):
                stage = recovery.destination/STAGE
                if kind == 'hardlink': os.link(archive, stage)
                elif kind == 'file': stage.write_bytes(b'partial bytes')
                elif kind == 'directory': stage.mkdir()
                else: stage.symlink_to(recovery.state/'missing')
                with self.assertRaises(OperationDenied): recovery.inspect()
                self.assertTrue(os.path.lexists(stage))
                self.assertTrue(archive.exists())

    def test_confirmation_is_exact_and_required(self):
        with self.fixture() as (recovery, archive):
            token = recovery.inspect()['confirmation_token']
            for confirmed in (False, 1, 'yes'):
                with self.assertRaises(OperationDenied):
                    recovery.keep_archives(token, confirmed=confirmed)
            with self.assertRaises(OperationDenied):
                recovery.keep_archives('stale token', confirmed=True)
            os.utime(archive, ns=(archive.stat().st_atime_ns, archive.stat().st_mtime_ns + 1000))
            with self.assertRaises(OperationDenied): recovery.keep_archives(token, confirmed=True)
            self.assertTrue(intent.pending(recovery.state))
            self.assertEqual(len(recovery.history.list()), 1)

    def test_outstanding_snapshot_wrong_kind_and_active_phase_block(self):
        for field, value in (('snapshot_id', 'test/config@pcc-backup-outstanding'),
                             ('kind', 'RESTORE'), ('phase', Phase.RUNNING)):
            with self.subTest(field=field), self.fixture() as (recovery, _):
                with recovery.store.transaction() as operation: setattr(operation, field, value)
                with self.assertRaises(OperationDenied): recovery.inspect()
                self.assertTrue(intent.pending(recovery.state))

    def test_dual_or_malformed_record_block(self):
        for dual in (False, True):
            with self.subTest(dual=dual), self.fixture() as (recovery, _):
                (recovery.state/(intent.REPLACEMENT_MARKER if dual else intent.MARKER)).write_bytes(b'bad')
                with self.assertRaises((ValueError, OperationDenied)): recovery.inspect()
                self.assertTrue(intent.pending(recovery.state))

    def test_failed_checkpoint_still_blocks_deletion_and_startup_reblocks(self):
        with self.fixture() as (recovery, _):
            with recovery.store.transaction() as operation: operation.phase = Phase.FAILED
            archives = ArchiveStore(recovery.destination, recovery.state)
            with self.assertRaises(OperationBusy): archives.delete(archives.list(), confirmed=True)
            reconcile_startup(recovery.store, recovery.progress, recovery.history, recovery.state)
            self.assertEqual(self.phase(recovery), Phase.RECOVERY_REQUIRED)
            recovery.keep_archives(recovery.inspect()['confirmation_token'], confirmed=True)
            self.assertFalse(intent.pending(recovery.state))

    def test_clear_failure_keeps_block_and_all_archives(self):
        with self.fixture() as (recovery, archive):
            token = recovery.inspect()['confirmation_token']
            with patch('plexconfigcontrol.publication_recovery.intent.clear', side_effect=OSError('disk')):
                with self.assertRaises(OSError): recovery.keep_archives(token, confirmed=True)
            self.assertEqual(self.phase(recovery), Phase.RECOVERY_REQUIRED)
            self.assertTrue(intent.pending(recovery.state))
            self.assertTrue(archive.exists())
            self.assertEqual(recovery.progress.read()['stage'], 'FAILED')

    def test_post_unlink_durability_failure_still_blocks(self):
        with self.fixture() as (recovery, archive):
            token = recovery.inspect()['confirmation_token']
            def ambiguous(directory):
                (Path(directory)/intent.MARKER).unlink()
                raise OSError('directory fsync failed')
            with patch('plexconfigcontrol.publication_recovery.intent.clear', side_effect=ambiguous):
                with self.assertRaises(OSError): recovery.keep_archives(token, confirmed=True)
            self.assertFalse(intent.pending(recovery.state))
            self.assertEqual(self.phase(recovery), Phase.RECOVERY_REQUIRED)
            archives = ArchiveStore(recovery.destination, recovery.state)
            with self.assertRaises(OperationBusy): archives.delete(archives.list(), confirmed=True)
            self.assertTrue(archive.exists())

    def test_log_failure_leaves_marker_and_phase(self):
        with self.fixture() as (recovery, archive):
            token = recovery.inspect()['confirmation_token']
            with patch('plexconfigcontrol.publication_recovery.EventLog', side_effect=OSError('read only')):
                with self.assertRaises(OSError): recovery.keep_archives(token, confirmed=True)
            self.assertTrue(intent.pending(recovery.state))
            self.assertEqual(self.phase(recovery), Phase.RECOVERY_REQUIRED)

    def test_operation_lock_serializes_confirmation(self):
        with self.fixture() as (recovery, _):
            with operation_lock(recovery.state):
                with self.assertRaises(OperationBusy): recovery.inspect()

    def test_already_retired_old_file_is_not_reported_retained(self):
        with self.fixture(replacement=True) as (recovery, archive):
            (recovery.destination/OLD).unlink()
            report = recovery.inspect()
            self.assertEqual(report['older_archive_state'], 'ABSENT')
            self.assertIsNone(report['retained_older_archive'])
            recovery.keep_archives(report['confirmation_token'], confirmed=True)
            self.assertTrue(archive.exists())

    def test_unexpected_progress_blocks_before_state_checkpoint(self):
        with self.fixture() as (recovery, _):
            recovery.progress.start('RESTORE', now=200)
            with self.assertRaises(ValueError):
                recovery.keep_archives(recovery.inspect()['confirmation_token'], confirmed=True)
            self.assertTrue(intent.pending(recovery.state))
            self.assertEqual(self.phase(recovery), Phase.RECOVERY_REQUIRED)

    def test_real_backup_failure_is_recoverable_without_more_host_calls(self):
        from test_backup_overwrite import ReplacementTests, NEW as BACKUP_NAME
        for replacement in (False, True):
            with self.subTest(replacement=replacement), ReplacementTests().fixture() as fixture:
                backup, selected, old, api, store, history, progress = fixture
                target = ('plexconfigcontrol.backup.retire_original' if replacement
                          else 'plexconfigcontrol.backup.publication_intent.clear')
                with patch(target, side_effect=OSError('injected interruption')):
                    with self.assertRaises(OSError):
                        if replacement: backup.run_overwrite(selected)
                        else: backup.run_new(create_another=selected)
                self.assertTrue((backup.destination/BACKUP_NAME).exists())
                self.assertTrue(old.exists())
                self.assertEqual(api.present, set())
                before = list(api.calls)
                recovery = PublicationRecovery(store, history, progress, backup.state, backup.destination)
                report = recovery.inspect()
                recovery.keep_archives(report['confirmation_token'], confirmed=True)
                self.assertEqual(api.calls, before)
                self.assertTrue(old.exists())
                self.assertEqual(self.phase(recovery), Phase.FAILED)
                self.assertFalse(intent.pending(backup.state))
