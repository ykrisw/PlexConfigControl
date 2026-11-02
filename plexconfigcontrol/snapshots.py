"""Dataset-scoped snapshot coordinator over an injected TrueNAS API client.

The API key itself may have broader privileges. This restricts application calls;
transport authentication, TLS and durable coordinator integration are separate.
"""
import re
import uuid

class SnapshotError(RuntimeError):
    pass

class Snapshots:
    def __init__(self, api, store, dataset):
        if not dataset or '@' in dataset or any(p in ('', '.', '..') for p in dataset.split('/')):
            raise ValueError('Invalid dataset')
        self.api, self.store, self.dataset = api, store, dataset

    def _check(self, identifier):
        prefix = self.dataset + '@'
        if not identifier.startswith(prefix) or not re.fullmatch(r'pcc-(backup|restore)-[0-9a-f]{32}', identifier[len(prefix):]):
            raise SnapshotError('Snapshot is outside the configured scope')

    def create(self):
        # Persist intent before network I/O. A timeout leaves this exact identity
        # outstanding, including if TrueNAS created it but the reply was lost.
        with self.store.transaction() as operation:
            if operation.kind not in ('BACKUP', 'RESTORE'):
                raise SnapshotError('No active operation')
            name = 'pcc-' + operation.kind.lower() + '-' + uuid.uuid4().hex
            operation.record_snapshot_intent(self.dataset, name)
            identifier = operation.snapshot_id
        self.api.call('pool.snapshot.create', {
            'dataset': self.dataset, 'name': name, 'recursive': False,
        })
        if not self.exists(identifier):
            raise SnapshotError('Snapshot creation was not confirmed')
        return identifier

    def exists(self, identifier):
        self._check(identifier)
        return bool(self.api.call('pool.snapshot.query', [['id', '=', identifier]]))

    def remove(self):
        # Caller must hold the operation-wide lock, and require web confirmation
        # for manual removal. No deletion during an active archive/rollback task.
        with self.store.transaction() as operation:
            identifier = operation.snapshot_id
        if not identifier:
            raise SnapshotError('No outstanding snapshot')
        self._check(identifier)
        if self.exists(identifier):
            self.api.call('pool.snapshot.delete', identifier,
                          {'defer': False, 'recursive': False})
        if self.exists(identifier):
            raise SnapshotError('Snapshot remains; new operations must stay blocked')
        with self.store.transaction() as operation:
            operation.confirm_snapshot_absent(identifier)

    def rollback(self):
        with self.store.transaction() as operation:
            if operation.kind != 'RESTORE':
                raise SnapshotError('Rollback is only available for Restore')
            identifier = operation.snapshot_id
        if not identifier:
            raise SnapshotError('No recovery snapshot')
        self._check(identifier)
        apps = self.api.call('app.query', [['name', '=', 'plex']])
        if len(apps) != 1 or apps[0].get('state') != 'STOPPED':
            raise SnapshotError('Plex must be confirmed STOPPED before rollback')
        if not self.exists(identifier):
            raise SnapshotError('Recovery snapshot is missing')
        self.api.call('pool.snapshot.rollback', identifier, {
            'recursive': False, 'recursive_clones': False,
            'force': False, 'recursive_rollback': False,
        })
        # Never clear snapshot intent here: rollback data must be independently
        # verified and a failed Restore retains its emergency snapshot.
