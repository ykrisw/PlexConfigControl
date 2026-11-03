"""Portable, single-file backups: byte-only copy, fresh app state and Restore.

GNU tar and SQLite run for real on temporary files. ZFS/Plex are simulated;
these checks neither mount SMB nor contact a NAS.
"""
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from plexconfigcontrol.archive_store import ArchiveStore
from plexconfigcontrol.archives import BASE, REQUIRED, InvalidArchive, validate_archive
from plexconfigcontrol.backup import Backup
from plexconfigcontrol.backup_archive import create_archive
from plexconfigcontrol.history import History
from plexconfigcontrol.operations import Phase, OperationDenied
from plexconfigcontrol.progress import Progress
from plexconfigcontrol.restore import Restore
from plexconfigcontrol.restore_readiness import restore_readiness
from plexconfigcontrol.restore_validation import RestoreValidation
from plexconfigcontrol.staging import stage_archive
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.web import Web
from test_snapshots import API

NAME = 'TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'


class Host(API):
    def __init__(self):
        super().__init__()
        self.plex_state = 'RUNNING'

    def call(self, method, *args):
        if method == 'app.query':
            self.calls.append((method, args))
            return [{'name': 'plex', 'state': self.plex_state}]
        return super().call(method, *args)


def config_fixture(directory):
    """Include valid databases, non-ASCII paths, private files and empty dirs."""
    directory.mkdir()
    for name in REQUIRED:
        path = directory/name.removeprefix('config/')
        path.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith('.db'):
            with sqlite3.connect(path) as database:
                database.execute('CREATE TABLE fixture (title TEXT, data BLOB)')
                database.execute('INSERT INTO fixture VALUES (?, ?)', ('Zażółć — Film', b'\x00\xff\x01'))
        else:
            path.write_bytes(b'<?xml version="1.0"?><Preferences Fixture="portable"/>')
    plex = directory/BASE.removeprefix('config/')
    (plex/'.LocalAdminToken').write_bytes(b'fixture-token-only')
    (plex/'cert-v2.p12').write_bytes(bytes(range(256)))
    (plex/'Metadata'/'Żółty film — 日本語').mkdir(parents=True)
    (plex/'Metadata'/'Żółty film — 日本語'/'poster.bin').write_bytes(bytes(range(256))*4)
    (plex/'empty directory').mkdir()
    for path in directory.rglob('*'):
        path.chmod(0o750 if path.is_dir() else 0o640)
        os.utime(path, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    token = plex/'.LocalAdminToken'
    token.chmod(0o600)
    xattrs = False
    try:
        os.setxattr(token, 'user.pcc_fixture', b'embedded metadata')
        xattrs = True
    except OSError:
        pass  # Some local/CI filesystems do not support user xattrs.
    return xattrs


def inventory(directory, include_xattrs=False):
    result = {}
    for path in directory.rglob('*'):
        info = path.stat()
        attrs = {key: os.getxattr(path, key) for key in os.listxattr(path)} if include_xattrs else {}
        result[path.relative_to(directory).as_posix()] = (
            path.is_dir(), None if path.is_dir() else path.read_bytes(),
            info.st_mode & 0o7777, info.st_uid, info.st_gid, info.st_mtime_ns, attrs)
    return result


def check_databases(directory):
    for name in REQUIRED:
        if not name.endswith('.db'):
            continue
        path = directory/name.removeprefix('config/')
        with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as database:
            if database.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise RuntimeError('Fixture database integrity failed')
            if database.execute('SELECT title, data FROM fixture').fetchone() != ('Zażółć — Film', b'\x00\xff\x01'):
                raise RuntimeError('Fixture database content changed')


class PortableArchiveTests(unittest.TestCase):
    def test_backup_copied_out_and_back_restores_without_history_sidecars_or_original_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state, destination = root/'original app state', root/'Plex Config'
            (destination/'Logs').mkdir(parents=True)
            snapshot = root/'snapshot'
            xattrs = config_fixture(snapshot)
            expected = inventory(snapshot, xattrs)
            host = Host()
            @contextmanager
            def reader(identifier):
                self.assertIn(identifier, host.present)
                yield snapshot
            history = History(state)
            backup = Backup(host, StateStore(state), history, Progress(state), state,
                            destination, 'test/config', reader)
            name = backup.run_new()
            original = destination/name
            digest = hashlib.sha256(original.read_bytes()).hexdigest()
            self.assertEqual(host.present, set())
            # copyfile deliberately does not preserve the container file's ACL,
            # ownership, mtime or xattrs. FAT/NTFS/SMB need preserve only bytes.
            external = root/'external storage'
            external.mkdir()
            shutil.copyfile(original, external/name)
            external_file = external/name
            external_file.chmod(0o600)
            os.utime(external_file, (1234567890, 1234567890))
            self.assertEqual([path.name for path in external.iterdir()], [name])
            original_identity = ArchiveStore(destination, state).list()[0]
            logs_before = {path.name: path.read_bytes() for path in (destination/'Logs').iterdir()}
            history.clear([event['id'] for event in history.list()])
            ArchiveStore(destination, state).delete([original_identity], confirmed=True)
            self.assertEqual(ArchiveStore(destination, state).list(), [])
            shutil.rmtree(snapshot)  # Backup must not depend on its source.
            shutil.rmtree(state)     # Or on the original ixVolume/history.
            shutil.copyfile(external_file, original)
            original.chmod(0o640)
            os.utime(original, (1700000000, 1700000000))
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), digest)
            # All original operation logs remain untouched by export/history clear.
            self.assertEqual({path.name: path.read_bytes() for path in (destination/'Logs').iterdir()}, logs_before)
            fresh = root/'new app state'
            store, history, progress = StateStore(fresh), History(fresh), Progress(fresh)
            listed = ArchiveStore(destination, fresh).list()
            self.assertEqual([item.name for item in listed], [name])
            self.assertNotEqual(listed[0].modified_ns, original_identity.modified_ns)
            self.assertEqual(history.list(), [])
            validator = RestoreValidation(destination, fresh, store, history)
            validated = validator.validate(name)
            self.assertEqual(validated['sha256'], digest)
            self.assertEqual(host.plex_state, 'RUNNING')
            self.assertFalse(restore_readiness(store, fresh, host, destination)['ready'])
            with stage_archive(original, fresh, digest) as staged:
                self.assertEqual(inventory(staged, xattrs), expected)
                check_databases(staged)
            self.assertEqual(list(fresh.glob('restore-*')), [])
            target = root/'restored isolated config'
            writes = []
            def write(staged):
                writes.append(True)
                shutil.copytree(staged, target)
            def verify(staged):
                check_databases(target)
                return inventory(target, xattrs) == expected
            restore = Restore(host, store, history, progress, fresh, destination,
                              'test/config', check_databases, write, verify, lambda _: False)
            # Neither a valid portable file nor a copied validation result can
            # bypass the user's manual stop and RESTORE confirmation.
            with self.assertRaises(OperationDenied):
                restore.run(name, 'RESTORE')
            self.assertEqual(writes, [])
            host.plex_state = 'STOPPED'  # Simulate manual action in TrueNAS Apps.
            self.assertTrue(restore_readiness(store, fresh, host, destination)['ready'])
            with self.assertRaises(OperationDenied):
                restore.run(name, '')
            restore.run(name, 'RESTORE')
            self.assertEqual(writes, [True])
            self.assertEqual(inventory(target, xattrs), expected)
            with store.transaction() as operation:
                self.assertEqual(operation.phase, Phase.SUCCESS)
                self.assertIsNone(operation.snapshot_id)
            self.assertEqual(host.present, set())
            self.assertEqual(host.plex_state, 'STOPPED')
            self.assertFalse(any(method in ('app.start', 'app.stop') for method, _ in host.calls))
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), digest)

    def test_copied_back_archive_is_discovered_and_validated_by_fresh_web_panel(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'source'
            config_fixture(source)
            external = root/'external'
            external.mkdir()
            created = create_archive(source, external/NAME)
            destination = root/'Plex Config'
            destination.mkdir()
            app = Web(root/'fresh state', destination, truenas_api=Host())
            token, csrf = app.sessions.create()
            def request(path, body=None):
                data = json.dumps(body).encode() if body is not None else b''
                status = []
                result = b''.join(app({'REQUEST_METHOD': 'POST' if body is not None else 'GET',
                    'PATH_INFO': path, 'CONTENT_TYPE': 'application/json',
                    'CONTENT_LENGTH': str(len(data)), 'wsgi.input': io.BytesIO(data),
                    'HTTP_COOKIE': 'pcc_session='+token, 'HTTP_X_CSRF_TOKEN': csrf},
                    lambda code, headers: status.append(code)))
                return status[0], json.loads(result)
            self.assertEqual(request('/api/archives')[1], [])
            shutil.copyfile(external/NAME, destination/NAME)
            status, listed = request('/api/archives')
            self.assertEqual(status, '200 OK')
            self.assertEqual([item['name'] for item in listed], [NAME])
            self.assertEqual(app.history.list(), [])
            status, result = request('/api/restore/validate', {'archive': NAME})
            self.assertEqual(status, '200 OK')
            self.assertEqual(result['sha256'], created.sha256)
            self.assertEqual(result['phase'], 'WAITING_FOR_PLEX_STOP')

    def test_incomplete_copy_is_rejected_then_complete_copy_can_be_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_fixture(root/'source')
            created = create_archive(root/'source', root/'external.tar.gz')
            destination, state = root/'Plex Config', root/'state'
            destination.mkdir()
            data = (root/'external.tar.gz').read_bytes()
            (destination/NAME).write_bytes(data[:len(data)//2])
            store, history = StateStore(state), History(state)
            validator = RestoreValidation(destination, state, store, history)
            with self.assertRaises(InvalidArchive):
                validator.validate(NAME)
            with store.transaction() as operation:
                self.assertEqual(operation.phase, Phase.FAILED)
                self.assertIsNone(operation.snapshot_id)
            shutil.copyfile(root/'external.tar.gz', destination/NAME)
            self.assertEqual(validator.validate(NAME)['sha256'], created.sha256)
            with store.transaction() as operation:
                self.assertEqual(operation.phase, Phase.WAITING_FOR_PLEX_STOP)
                self.assertIsNone(operation.snapshot_id)

    def test_replacing_a_validated_copy_requires_revalidation_even_for_identical_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_fixture(root/'source')
            destination, state = root/'Plex Config', root/'state'
            destination.mkdir()
            created = create_archive(root/'source', destination/NAME)
            shutil.copyfile(destination/NAME, root/'external.tar.gz')
            store, history, host = StateStore(state), History(state), Host()
            host.plex_state = 'STOPPED'
            validator = RestoreValidation(destination, state, store, history)
            validator.validate(NAME)
            self.assertTrue(restore_readiness(store, state, host, destination)['ready'])
            # Create another inode before unlinking the selected one.
            shutil.copyfile(root/'external.tar.gz', destination/'incoming.tmp')
            os.replace(destination/'incoming.tmp', destination/NAME)
            readiness = restore_readiness(store, state, host, destination)
            self.assertFalse(readiness['ready'])
            self.assertEqual(readiness['reason'], 'ARCHIVE_CHANGED_REVALIDATE')
            restore = Restore(host, store, history, Progress(state), state, destination,
                              'test/config', lambda _: self.fail('Database check must not run'),
                              lambda _: self.fail('No config write permitted'),
                              lambda _: self.fail('No config verification permitted'), lambda _: False)
            host.calls.clear()
            with self.assertRaises(OperationDenied):
                restore.run(NAME, 'RESTORE')
            self.assertEqual(host.calls, [])
            self.assertEqual(host.present, set())
            validator.cancel()
            self.assertEqual(validator.validate(NAME)['sha256'], created.sha256)
            self.assertTrue(restore_readiness(store, state, host, destination)['ready'])


    def test_copy_replaced_during_database_check_never_creates_emergency_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_fixture(root/'source')
            destination, state = root/'Plex Config', root/'state'
            (destination/'Logs').mkdir(parents=True)
            create_archive(root/'source', destination/NAME)
            shutil.copyfile(destination/NAME, root/'external.tar.gz')
            store, history, host = StateStore(state), History(state), Host()
            host.plex_state = 'STOPPED'
            RestoreValidation(destination, state, store, history).validate(NAME)
            def check(staged):
                check_databases(staged)
                shutil.copyfile(root/'external.tar.gz', destination/'incoming.tmp')
                os.replace(destination/'incoming.tmp', destination/NAME)
            restore = Restore(host, store, history, Progress(state), state, destination,
                              'test/config', check, lambda _: self.fail('No config write permitted'),
                              lambda _: True, lambda _: False)
            with self.assertRaises(OperationDenied):
                restore.run(NAME, 'RESTORE')
            self.assertFalse(any(method.startswith('pool.snapshot.') for method, _ in host.calls))
            self.assertEqual(host.present, set())
            self.assertEqual(host.plex_state, 'STOPPED')
            with store.transaction() as operation:
                self.assertEqual(operation.phase, Phase.FAILED)
                self.assertIsNone(operation.snapshot_id)

    def test_copy_damage_after_selection_is_rejected_without_config_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_fixture(root/'source')
            destination, state = root/'Plex Config', root/'state'
            (destination/'Logs').mkdir(parents=True)
            create_archive(root/'source', destination/NAME)
            store, history, host = StateStore(state), History(state), Host()
            host.plex_state = 'STOPPED'
            RestoreValidation(destination, state, store, history).validate(NAME)
            original_bytes = (destination/NAME).read_bytes()
            restore = Restore(host, store, history, Progress(state), state, destination,
                              'test/config', check_databases,
                              lambda _: self.fail('No config write permitted'), lambda _: True, lambda _: False)
            # Even if a faulty/stale identity check were to miss an external edit,
            # staging independently compares all copied bytes with the digest.
            damaged = bytearray(original_bytes)
            damaged[len(damaged)//2] ^= 0xff
            (destination/NAME).write_bytes(damaged)
            with patch('plexconfigcontrol.restore.archive_matches', return_value=True):
                with self.assertRaises((InvalidArchive, RuntimeError)):
                    restore.run(NAME, 'RESTORE')
            self.assertFalse(any(method.startswith('pool.snapshot.') for method, _ in host.calls))
            self.assertEqual(host.present, set())
            self.assertEqual(list(state.glob('restore-*')), [])
