"""Opt-in real TrueNAS smoke test, restricted to a fresh disposable dataset.

Uses application snapshot/state/reader modules. No Plex configuration mounts,
archive restores, application stop/start, or production RPC credentials involved.
The local midclt adapter is test-only and must never be used by the web runtime.
"""
import argparse
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from plexconfigcontrol.plex import PlexStatus
from plexconfigcontrol.snapshot_reader import SnapshotReader, SnapshotReadError
from plexconfigcontrol.snapshots import Snapshots
from plexconfigcontrol.state import StateStore


class SandboxAPI:
    def __init__(self, dataset, runner=subprocess.run):
        if not re.fullmatch(r'TrueNAS/pcc-test-[0-9a-f]{32}', dataset):
            raise ValueError('Fresh sandbox dataset required')
        self.dataset, self.runner = dataset, runner
        self.owned_snapshots = set()

    def call(self, method, *args):
        d = self.dataset
        permitted = False
        if method == 'app.query':
            permitted = args == ([['name', '=', 'plex']],)
        elif method == 'pool.dataset.query':
            permitted = args == ([['id', '=', d]],)
        elif method == 'pool.dataset.create':
            permitted = args == ({'name': d, 'type': 'FILESYSTEM',
                'share_type': 'GENERIC', 'acltype': 'POSIX', 'refquota': 1073741824},)
        elif method == 'pool.dataset.delete':
            permitted = args == (d, {'recursive': False, 'force': False})
        elif method == 'pool.snapshot.create' and len(args) == 1:
            data = args[0]
            permitted = (isinstance(data, dict) and set(data) == {'dataset', 'name', 'recursive'}
                and data['dataset'] == d and data['recursive'] is False
                and isinstance(data['name'], str)
                and re.fullmatch(r'pcc-backup-[0-9a-f]{32}', data['name']) is not None)
            if permitted:
                self.owned_snapshots.add(d + '@' + data['name'])
        elif method == 'pool.snapshot.query' and len(args) == 1:
            permitted = any(args == ([['id', '=', identifier]],)
                            for identifier in self.owned_snapshots)
        elif method == 'pool.snapshot.delete' and len(args) == 2:
            permitted = (isinstance(args[0], str) and args[0] in self.owned_snapshots
                and args[1] == {'defer': False, 'recursive': False})
        if not permitted:
            raise ValueError('Host test call outside sandbox scope')
        result = self.runner(['midclt', 'call', method, *map(json.dumps, args)],
                             text=True, capture_output=True, timeout=90)
        if result.returncode:
            raise RuntimeError(method + ' failed: ' + result.stderr.strip())
        # midclt renders scalar results as Python text (e.g. True), and
        # void results can be empty. Mutation output is not an absence proof.
        # Callers independently query the exact dataset/snapshot afterwards.
        # Keep read queries strict: empty or malformed output is never absence.
        if method in ('app.query', 'pool.dataset.query', 'pool.snapshot.query'):
            return json.loads(result.stdout)
        return None


def write(path, data, *, new=False):
    with path.open('xb' if new else 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def archive_fixture(root):
    """Synthetic Plex-shaped files, never copied from the live Plex dataset."""
    import sqlite3
    from plexconfigcontrol.archives import REQUIRED
    for member in REQUIRED:
        path = root / member.removeprefix('config/')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == '.db':
            connection = sqlite3.connect(path)
            try:
                connection.execute('CREATE TABLE fixture (value TEXT)')
                connection.execute("INSERT INTO fixture VALUES ('synthetic test data')")
                connection.commit()
            finally:
                connection.close()
        else:
            write(path, b'<Preferences Fixture="true"/>', new=True)


def exercise_archive(source, workspace):
    """Actual GNU tar creation, full validation, portable copy and corruption."""
    import shutil
    from datetime import datetime, timezone
    from plexconfigcontrol.archives import archive_name, validate_archive, InvalidArchive
    from plexconfigcontrol.backup_archive import create_archive
    root = Path(workspace)
    original = root / archive_name(datetime.now(timezone.utc))
    validation = create_archive(source, original)
    print('APPLICATION TAR + GZIP + FULL SNAPSHOT CONTENT COMPARISON: OK', flush=True)
    exported = root / 'external-location'
    returned = root / 'returned-location'
    exported.mkdir(); returned.mkdir()
    export_copy = exported / original.name
    returned_copy = returned / original.name
    shutil.copyfile(original, export_copy)
    shutil.copyfile(export_copy, returned_copy)
    imported = validate_archive(returned_copy)
    if imported != validation:
        raise RuntimeError('Portable archive copy changed content or validation result')
    print('COPY OUT + COPY BACK + IDENTICAL SHA256/FULL VALIDATION: OK', flush=True)
    broken = root / 'damaged-test-copy.tar.gz'
    data = original.read_bytes()
    broken.write_bytes(data[:-8])
    try:
        validate_archive(broken)
    except InvalidArchive:
        print('TRUNCATED ARCHIVE REJECTED: OK', flush=True)
    else:
        raise RuntimeError('Truncated archive was accepted')
    return validation


def exercise_backup(api, dataset, root, info, workspace):
    """Real Backup coordinator, synthetic source and RAM-only destination/state."""
    import tarfile
    from contextlib import contextmanager
    from plexconfigcontrol.backup import Backup, BackupDecisionRequired
    from plexconfigcontrol.archives import validate_archive
    from plexconfigcontrol.archive_store import ArchiveStore
    from plexconfigcontrol.history import History
    from plexconfigcontrol.operations import Phase
    from plexconfigcontrol.progress import Progress
    from plexconfigcontrol import publication_intent
    base = Path(workspace)
    state = base/'state'
    destination = base/'Plex Config'
    (destination/'Logs').mkdir(parents=True)
    store = StateStore(state)
    history = History(state)
    progress = Progress(state)
    reader = SnapshotReader(root, dataset, info.st_dev, info.st_ino, api)
    expected = (root/'fixture.bin').read_bytes()

    @contextmanager
    def immutable_reader(identifier):
        with reader(identifier) as snapshot:
            # Deliberately change ONLY the live sandbox after snapshot creation.
            # The resulting archive must still contain the pre-change bytes.
            write(root/'fixture.bin', b'live sandbox changed during backup\n')
            yield snapshot

    backup = Backup(api, store, history, progress, state, destination,
                    dataset, immutable_reader)
    name = backup.run_new()
    result = validate_archive(destination/name)
    with tarfile.open(destination/name, 'r:gz') as archive:
        with archive.extractfile('config/fixture.bin') as stream:
            if stream.read() != expected:
                raise RuntimeError('Backup archived live data instead of snapshot data')
    with store.transaction() as operation:
        if (operation.phase != Phase.SUCCESS or operation.snapshot_id is not None
                or operation.outcome != {'code':'BACKUP_COMPLETED', 'archive':name}):
            raise RuntimeError('Backup terminal state was not confirmed')
    if publication_intent.pending(state):
        raise RuntimeError('Backup publication intent remains unresolved')
    if progress.read()['stage'] != 'COMPLETED':
        raise RuntimeError('Backup progress did not finish')
    if len(ArchiveStore(destination, state).list()) != 1:
        raise RuntimeError('Backup archive listing does not match publication')
    if any(path.name.startswith('backup-') for path in state.iterdir()):
        raise RuntimeError('Private backup workspace remains')
    events = history.list()
    logs = {path.name:path.read_bytes() for path in (destination/'Logs').glob('*.log')}
    if (len(events) != 1 or events[0]['kind'] != 'BACKUP'
            or events[0]['status'] != 'SUCCESS' or events[0]['archive'] != name
            or len(logs) != 1):
        raise RuntimeError('Backup history or diagnostic log is incomplete')
    print('BACKUP COORDINATOR + SNAPSHOT-ONLY DATA + PUBLICATION + SUCCESS STATE: OK', flush=True)
    before = set(api.owned_snapshots)
    try:
        backup.run_new()
    except BackupDecisionRequired as question:
        if question.archive.name != name:
            raise RuntimeError('Single-copy prompt selected another archive')
    else:
        raise RuntimeError('Second-copy confirmation was not required')
    if set(api.owned_snapshots) != before or len(history.list()) != 1:
        raise RuntimeError('Single-copy question unexpectedly started an operation')
    print('ONE EXISTING COPY REQUIRES A DECISION BEFORE ANOTHER SNAPSHOT: OK', flush=True)
    history.clear([events[0]['id']])
    if history.list() or logs != {path.name:path.read_bytes()
                                 for path in (destination/'Logs').glob('*.log')}:
        raise RuntimeError('History clear changed diagnostic logs')
    if validate_archive(destination/name) != result:
        raise RuntimeError('History clear changed the archive')
    print('HISTORY CLEAR PRESERVES ARCHIVE AND DIAGNOSTIC LOG BYTES: OK', flush=True)


def run(*, archive_test=False, backup_test=False):
    if os.geteuid() != 0:
        raise RuntimeError('Run through sudo')
    dataset = 'TrueNAS/pcc-test-' + uuid.uuid4().hex
    api = SandboxAPI(dataset)
    created = False
    print('TEST DATASET:', dataset, flush=True)
    try:
        before = PlexStatus(api).read()
        if before['state'] != 'RUNNING':
            raise RuntimeError('Plex must already be RUNNING for this backup smoke test')
        if api.call('pool.dataset.query', [['id', '=', dataset]]) != []:
            raise RuntimeError('Sandbox name is already occupied')
        # Print identity before the first mutation; uncertain creation is retained.
        created = True
        api.call('pool.dataset.create', {'name': dataset, 'type': 'FILESYSTEM',
            'share_type': 'GENERIC', 'acltype': 'POSIX', 'refquota': 1073741824})
        root = Path('/mnt') / dataset
        mount = subprocess.check_output(['zfs', 'get', '-H', '-o', 'value',
                                         'mountpoint', dataset], text=True).strip()
        if mount != str(root) or root.resolve(strict=True) != root:
            raise RuntimeError('Unexpected sandbox mount')
        info = root.stat()
        original = b'PCC immutable snapshot fixture\n'
        write(root/'fixture.bin', original, new=True)
        if archive_test or backup_test:
            archive_fixture(root)
        with tempfile.TemporaryDirectory(prefix='pcc-host-state-', dir='/dev/shm') as state:
            store = StateStore(state)
            with store.transaction() as operation:
                operation.begin('BACKUP')
                operation.begin_backup()
            snapshots = Snapshots(api, store, dataset)
            identifier = snapshots.create()
            reopened = StateStore(state)
            with reopened.transaction() as operation:
                if operation.snapshot_id != identifier:
                    raise RuntimeError('Snapshot intent was not persisted')
            print('APPLICATION SNAPSHOT CREATE + PERSISTED INTENT: OK', flush=True)
            reader = SnapshotReader(root, dataset, info.st_dev, info.st_ino, api)
            write(root/'fixture.bin', b'changed live sandbox fixture\n')
            with reader(identifier) as source:
                if (source/'fixture.bin').read_bytes() != original:
                    raise RuntimeError('Snapshot contents changed')
                if not os.statvfs(source).f_flag & os.ST_RDONLY:
                    raise RuntimeError('Snapshot is writable')
                if archive_test:
                    with tempfile.TemporaryDirectory(prefix='pcc-archive-test-', dir='/dev/shm') as workspace:
                        exercise_archive(source, workspace)
            print('APPLICATION SNAPSHOT READER + READ-ONLY CHECK: OK', flush=True)
            try:
                with reader('TrueNAS/not-this-dataset@pcc-backup-'+'a'*32):
                    raise RuntimeError('Foreign snapshot was accepted')
            except SnapshotReadError:
                pass
            print('FOREIGN DATASET REJECTED: OK', flush=True)
            # All reader handles have been closed before deletion.
            snapshots.remove()
            if snapshots.exists(identifier):
                raise RuntimeError('Snapshot still present')
            with reopened.transaction() as operation:
                if operation.snapshot_id is not None:
                    raise RuntimeError('Confirmed deletion did not clear persisted intent')
                operation.finish(True)
            print('APPLICATION DELETE + ABSENCE QUERY + STATE CLEANUP: OK', flush=True)
        if backup_test:
            with tempfile.TemporaryDirectory(prefix='pcc-backup-test-', dir='/dev/shm') as workspace:
                exercise_backup(api, dataset, root, info, workspace)
        if PlexStatus(api).read()['state'] != 'RUNNING':
            raise RuntimeError('Plex is no longer RUNNING; investigate before continuing')
        api.call('pool.dataset.delete', dataset, {'recursive': False, 'force': False})
        if api.call('pool.dataset.query', [['id', '=', dataset]]) != []:
            raise RuntimeError('Sandbox deletion not confirmed')
        created = False
        print('PLEX RUNNING; TEST DATASET REMOVED: OK', flush=True)
        print('RESULT: PASS (selected host diagnostics; not full deployment acceptance)', flush=True)
    except BaseException:
        if created:
            print('STOP: do not rerun. Sandbox may remain:', dataset, flush=True)
            for identifier in sorted(api.owned_snapshots):
                print('Snapshot to inspect:', identifier, flush=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-sandbox-test', action='store_true', required=True)
    parser.add_argument('--archive-test', action='store_true')
    parser.add_argument('--backup-test', action='store_true')
    args = parser.parse_args()
    run(archive_test=args.archive_test, backup_test=args.backup_test)
