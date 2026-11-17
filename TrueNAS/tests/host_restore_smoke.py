"""Opt-in sandbox Restore success/failure using real Plex state; no app start/stop.

Requires Plex RUNNING initially to prove the real gate. Waits up to ten minutes
for the user to stop Plex manually, then restores synthetic data on one new
sandbox dataset. Failure mode requires Plex already STOPPED and retains one
emergency snapshot plus its sandbox for separately confirmed manual cleanup.
This is not a production configuration or UI acceptance test.
"""
import argparse
import os
import sqlite3
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from plexconfigcontrol.archives import archive_name
from plexconfigcontrol.backup_archive import create_archive
from plexconfigcontrol.config_writer import ConfigWriter
from plexconfigcontrol.history import History
from plexconfigcontrol.operations import OperationDenied, Phase
from plexconfigcontrol.plex import PlexStatus
from plexconfigcontrol.progress import Progress
from plexconfigcontrol.restore import Restore
from plexconfigcontrol.restore_validation import RestoreValidation
from plexconfigcontrol.rollback_verification import RollbackVerifier
from plexconfigcontrol.snapshot_reader import SnapshotReader
from plexconfigcontrol.snapshots import Snapshots
from plexconfigcontrol.state import StateStore
from tests.host_snapshot_smoke import SandboxAPI, archive_fixture, write


def wait_for_manual_stop(api, *, timeout=600, clock=time.monotonic, pause=time.sleep):
    deadline = clock()+timeout
    print('WAITING: Stop Plex MANUALLY in TrueNAS Apps. Maximum wait: 10 minutes.', flush=True)
    while True:
        state = PlexStatus(api).read()['state']
        if state == 'STOPPED':
            print('PLEX STOPPED CONFIRMED: OK', flush=True)
            return
        if state not in ('RUNNING', 'STOPPING'):
            raise RuntimeError('Plex state cannot be safely confirmed: '+state)
        if clock() >= deadline:
            raise TimeoutError('Manual Plex stop was not confirmed in time')
        pause(min(2, max(0, deadline-clock())))


def check_fixture_databases(config):
    directory = Path(config)/'Library/Application Support/Plex Media Server/Plug-in Support/Databases'
    for name in ('com.plexapp.plugins.library.db', 'com.plexapp.plugins.library.blobs.db'):
        connection = sqlite3.connect('file:'+quote(str(directory/name))+'?mode=ro', uri=True)
        try:
            if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise RuntimeError('Synthetic fixture database failed integrity check')
        finally:
            connection.close()


class InjectedRestoreFailure(RuntimeError):
    """Intentional failure after writes to the disposable sandbox only."""


def exercise_restore_failure(restore, name, api, store, snapshots, root,
                             progress, history, destination, verify_rollback):
    try:
        restore.run(name, 'RESTORE')
    except InjectedRestoreFailure:
        pass
    else:
        raise RuntimeError('The controlled Restore failure did not occur')
    with store.transaction() as operation:
        identifier = operation.snapshot_id
        if (operation.phase != Phase.RECOVERY_REQUIRED or not identifier
                or operation.outcome != {'code':'RESTORE_ROLLBACK_VERIFIED', 'archive':name}):
            raise RuntimeError('Restore did not report verified rollback with retained intent')
    if not snapshots.exists(identifier) or verify_rollback(identifier) is not True:
        raise RuntimeError('Retained rollback contents or snapshot not confirmed')
    if ((root/'fixture.bin').read_bytes() != b'Changed sandbox before Restore\n'
            or (root/'fixture.bin').stat().st_mode & 0o777 != 0o600
            or (root/'extra-before-restore.txt').read_bytes() != b'Restore should remove this\n'):
        raise RuntimeError('Rollback did not recover pre-Restore fixture contents/mode')
    present = [point for point in api.owned_snapshots if snapshots.exists(point)]
    if present != [identifier]:
        raise RuntimeError('Expected exactly one retained emergency snapshot')
    events = history.list()
    if not events or events[0]['kind'] != 'RESTORE' or events[0]['status'] != 'FAILED':
        raise RuntimeError('Controlled Restore failure was not recorded as FAILED')
    logs = list((destination/'Logs').glob('Restore_*.log'))
    if len(logs) != 1 or 'Rollback verified. Emergency snapshot retained.' not in logs[0].read_text():
        raise RuntimeError('Diagnostic log did not confirm rollback and retention')
    if progress.read()['stage'] != 'CLEANUP_REQUIRED':
        raise RuntimeError('Retained emergency snapshot was not reflected in progress')
    before = set(api.owned_snapshots)
    try:
        snapshots.create()
    except OperationDenied:
        pass
    else:
        raise RuntimeError('A second emergency snapshot was allowed')
    if api.owned_snapshots != before:
        raise RuntimeError('A second snapshot creation reached the host adapter')
    if any(path.name.startswith('restore-') for path in store.directory.iterdir()):
        raise RuntimeError('Private Restore staging remains')
    if PlexStatus(api).read()['state'] != 'STOPPED':
        raise RuntimeError('Plex did not remain STOPPED')
    print('CONTROLLED RESTORE FAILURE + REAL ROLLBACK + CONTENT/METADATA VERIFICATION: OK', flush=True)
    print('FAILED HISTORY/LOG + ONE RETAINED SNAPSHOT + SECOND SNAPSHOT BLOCKED: OK', flush=True)
    return identifier


def run(*, failure_test=False):
    from datetime import datetime, timezone
    if os.geteuid() != 0:
        raise RuntimeError('Run through sudo')
    dataset = 'TrueNAS/pcc-test-'+uuid.uuid4().hex
    api = SandboxAPI(dataset, allow_restore=True)
    created = False
    retained = None
    print('RESTORE TEST DATASET:', dataset, flush=True)
    try:
        initial = 'STOPPED' if failure_test else 'RUNNING'
        if PlexStatus(api).read()['state'] != initial:
            raise RuntimeError('This diagnostic requires initial Plex state: '+initial)
        if api.call('pool.dataset.query', [['id', '=', dataset]]) != []:
            raise RuntimeError('Sandbox name occupied')
        created = True
        api.call('pool.dataset.create', {'name':dataset, 'type':'FILESYSTEM',
            'share_type':'GENERIC', 'acltype':'POSIX', 'refquota':1073741824})
        root = Path('/mnt')/dataset
        mount = subprocess.check_output(['zfs', 'get', '-H', '-o', 'value',
                                         'mountpoint', dataset], text=True).strip()
        if mount != str(root) or root.resolve(strict=True) != root:
            raise RuntimeError('Unexpected sandbox mount')
        info = root.stat()
        archive_fixture(root)
        expected = b'Archive fixture to restore\n'
        write(root/'fixture.bin', expected, new=True)
        reader = SnapshotReader(root, dataset, info.st_dev, info.st_ino, api)
        with tempfile.TemporaryDirectory(prefix='pcc-restore-test-', dir='/dev/shm') as temporary:
            base = Path(temporary)
            destination = base/'Plex Config'
            (destination/'Logs').mkdir(parents=True)
            state = base/'state'
            store = StateStore(state)
            history = History(state)
            progress = Progress(state)
            with store.transaction() as operation:
                operation.begin('BACKUP'); operation.begin_backup()
            snapshots = Snapshots(api, store, dataset)
            identifier = snapshots.create()
            name = archive_name(datetime.now(timezone.utc))
            with reader(identifier) as source:
                create_archive(source, destination/name)
            snapshots.remove()
            with store.transaction() as operation:
                operation.finish(True)
            write(root/'fixture.bin', b'Changed sandbox before Restore\n')
            if failure_test:
                os.chmod(root/'fixture.bin', 0o600)
            write(root/'extra-before-restore.txt', b'Restore should remove this\n', new=True)
            RestoreValidation(destination, state, store, history).validate(name)
            status = PlexStatus(api)

            def writer():
                return ConfigWriter(root, info.st_dev, info.st_ino, status)

            def verify_restored(source):
                writer().verify(source)
                check_fixture_databases(root)
                return True

            def verify_rollback(snapshot_id):
                if RollbackVerifier(store, reader, writer())(snapshot_id) is not True:
                    return False
                check_fixture_databases(root)
                return True

            def write_restored(source):
                writer().write(source)
                if failure_test:
                    write(root/'fixture.bin', b'Injected failed Restore write\n')
                    raise InjectedRestoreFailure('Controlled failure on sandbox only')

            restore = Restore(api, store, history, progress, state, destination,
                dataset, check_fixture_databases, write_restored, verify_restored, verify_rollback)
            if failure_test:
                retained = exercise_restore_failure(restore, name, api, store, snapshots, root,
                    progress, history, destination, verify_rollback)
            else:
                before = set(api.owned_snapshots)
                try:
                    restore.run(name, 'RESTORE')
                except OperationDenied:
                    pass
                else:
                    raise RuntimeError('Restore was not blocked while Plex was RUNNING')
                with store.transaction() as operation:
                    if (operation.phase != Phase.WAITING_FOR_PLEX_STOP
                            or operation.snapshot_id is not None or operation.outcome is not None):
                        raise RuntimeError('Running-Plex rejection altered operation state')
                if before != api.owned_snapshots or list((destination/'Logs').iterdir()):
                    raise RuntimeError('Running-Plex rejection created a snapshot or Restore log')
                if ((root/'fixture.bin').read_bytes() != b'Changed sandbox before Restore\n'
                        or not (root/'extra-before-restore.txt').is_file()):
                    raise RuntimeError('Running-Plex rejection changed sandbox data')
                print('REAL RUNNING PLEX BLOCKS RESTORE BEFORE SNAPSHOT/WRITE: OK', flush=True)
                wait_for_manual_stop(api)
                restore.run(name, 'RESTORE')
                if ((root/'fixture.bin').read_bytes() != expected
                        or (root/'extra-before-restore.txt').exists()):
                    raise RuntimeError('Restored sandbox data mismatch')
                with store.transaction() as operation:
                    if (operation.phase != Phase.SUCCESS or operation.snapshot_id is not None
                            or operation.outcome != {'code':'RESTORE_COMPLETED', 'archive':name}):
                        raise RuntimeError('Restore success/checkpoint was not confirmed')
                if progress.read()['stage'] != 'COMPLETED':
                    raise RuntimeError('Restore progress is incomplete')
                events = history.list()
                if not events or events[0]['kind'] != 'RESTORE' or events[0]['status'] != 'SUCCESS':
                    raise RuntimeError('Restore History did not confirm success')
                logs = list((destination/'Logs').glob('Restore_*.log'))
                if len(logs) != 1 or 'Emergency snapshot absence confirmed' not in logs[0].read_text():
                    raise RuntimeError('Restore diagnostic log is incomplete')
                if any(path.name.startswith('restore-') for path in state.iterdir()):
                    raise RuntimeError('Private Restore staging remains')
                for identifier in api.owned_snapshots:
                    if snapshots.exists(identifier):
                        raise RuntimeError('Application snapshot remains')
                if PlexStatus(api).read()['state'] != 'STOPPED':
                    raise RuntimeError('Plex did not remain STOPPED')
                print('RESTORE COORDINATOR + REAL RSYNC + METADATA + FIXTURE DATABASES: OK', flush=True)
                print('SUCCESS/HISTORY/LOG + SNAPSHOT ABSENCE + STAGING CLEANUP: OK', flush=True)
        if retained:
            print('RETAINED TEST DATASET:', dataset, flush=True)
            print('RETAINED EMERGENCY SNAPSHOT:', retained, flush=True)
            print('PLEX REMAINS STOPPED. Manual confirmation required before removing the test snapshot.', flush=True)
            print('RESULT: PASS (expected failure recovered; test snapshot/dataset intentionally retained)', flush=True)
            return
        api.call('pool.dataset.delete', dataset, {'recursive':False, 'force':False})
        if api.call('pool.dataset.query', [['id', '=', dataset]]) != []:
            raise RuntimeError('Sandbox deletion was not confirmed')
        created = False
        print('TEST DATASET REMOVED; PLEX REMAINS STOPPED: OK', flush=True)
        print('RESULT: PASS (sandbox Restore success; failure/rollback and deployment remain untested)', flush=True)
    except BaseException:
        if created:
            print('STOP: do not rerun. Sandbox may remain:', dataset, flush=True)
            for identifier in sorted(api.owned_snapshots):
                print('Snapshot to inspect:', identifier, flush=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-sandbox-restore-test', action='store_true', required=True)
    parser.add_argument('--failure-test', action='store_true')
    args = parser.parse_args()
    run(failure_test=args.failure_test)
