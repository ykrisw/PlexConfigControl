"""Read-only rollback verification against the exact outstanding emergency snapshot.

Restore.run owns the operation lock. Deployment injects a scoped SnapshotReader
and ConfigWriter; this adapter accepts no arbitrary command, path or API method.
It never removes a snapshot, changes operation state or starts/stops Plex.
"""
from pathlib import Path

from .operations import OperationDenied, Phase


class RollbackVerifier:
    def __init__(self, store, snapshot_reader, config_writer):
        self.store = store
        self.reader = snapshot_reader
        self.writer = config_writer

    def _check_operation(self, identifier):
        with self.store.transaction() as operation:
            if (operation.kind != 'RESTORE' or operation.snapshot_id != identifier
                    or not isinstance(identifier, str) or '@' not in identifier
                    or operation.phase not in (Phase.RUNNING, Phase.RECOVERY_REQUIRED)):
                raise OperationDenied('Exact outstanding Restore snapshot required')

    def __call__(self, identifier):
        self._check_operation(identifier)
        with self.reader(identifier) as source:
            expected = self.writer.target/'.zfs'/'snapshot'/identifier.rsplit('@', 1)[1]
            if Path(source) != expected:
                raise OperationDenied('Snapshot reader returned an unexpected source')
            if self.writer.verify_snapshot(source) is not True:
                raise OperationDenied('Rollback content and metadata were not verified')
            self._check_operation(identifier)
        return True
