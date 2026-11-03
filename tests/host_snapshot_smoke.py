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
        # Void midclt methods can succeed with no output. Never infer absence
        # from that: application modules perform an independent exact query.
        return json.loads(result.stdout) if result.stdout.strip() else None


def write(path, data, *, new=False):
    with path.open('xb' if new else 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def run():
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
        if PlexStatus(api).read()['state'] != 'RUNNING':
            raise RuntimeError('Plex is no longer RUNNING; investigate before continuing')
        api.call('pool.dataset.delete', dataset, {'recursive': False, 'force': False})
        if api.call('pool.dataset.query', [['id', '=', dataset]]) != []:
            raise RuntimeError('Sandbox deletion not confirmed')
        created = False
        print('PLEX RUNNING; TEST DATASET REMOVED: OK', flush=True)
        print('RESULT: PASS (snapshot modules only; not a full Backup/Restore test)', flush=True)
    except BaseException:
        if created:
            print('STOP: do not rerun. Sandbox may remain:', dataset, flush=True)
            for identifier in sorted(api.owned_snapshots):
                print('Snapshot to inspect:', identifier, flush=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-sandbox-test', action='store_true', required=True)
    parser.parse_args()
    run()
