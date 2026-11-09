"""Build an execution owner from a trusted installation's fixed storage plan.

This is worker-side code. The browser and its runtime do not receive the
worker's TrueNAS credentials or its writable Plex mount.
"""
import re
import stat
from pathlib import Path

from .backup import Backup
from .config_writer import ConfigWriter
from .database_check import PlexDatabaseChecker
from .execution_worker import ExecutionWorker
from .history import History
from .operations import OperationDenied
from .plex import PlexStatus
from .plex_storage import PlexStorage, discover_plex_storage
from .progress import Progress
from .restore import Restore
from .rollback_verification import RollbackVerifier
from .snapshot_reader import SnapshotReader
from .snapshots import Snapshots
from .state import StateStore

_MOUNT_ESCAPES = {'040': ' ', '011': '\t', '012': '\n', '134': '\\'}


def _unescape_mount(field):
    return re.sub(r'\\(040|011|012|134)', lambda match: _MOUNT_ESCAPES[match[1]], field)


def _mounts():
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        before, after = line.split(' - ', 1)
        mount = before.split()
        filesystem, source, _ = after.split(maxsplit=2)
        yield Path(_unescape_mount(mount[4])), _unescape_mount(mount[3]), filesystem, _unescape_mount(source)


def _directory_identity(path):
    if not path.is_absolute() or path == Path('/') or path.resolve(strict=True) != path:
        raise OperationDenied('Execution directory must be an absolute path without symlinks')
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise OperationDenied('Execution directory is unavailable')
    return info.st_dev, info.st_ino


class ExecutionStorage:
    """Check the exact Plex mount in both TrueNAS and this execution environment."""
    def __init__(self, api, plan, config_mount, state, archives, *, mount_table=_mounts):
        if not isinstance(plan, PlexStorage) or not plan.dedicated_dataset_root:
            raise OperationDenied('A dedicated Plex configuration dataset is required')
        Snapshots(None, None, plan.dataset)
        self.api, self.plan, self.mount_table = api, plan, mount_table
        self.config, self.state, self.archives = map(Path, (config_mount, state, archives))
        locations = (self.config, self.state, self.archives)
        for index, first in enumerate(locations):
            for second in locations[index + 1:]:
                if first == second or first in second.parents or second in first.parents:
                    raise OperationDenied('Execution directories overlap')
        self._identities = {path: _directory_identity(path) for path in (*locations, self.archives/'Logs')}
        if len(set(self._identities.values())) != len(self._identities):
            raise OperationDenied('Execution directories resolve to the same storage')
        self.verify()

    @property
    def config_identity(self):
        return self._identities[self.config]

    def verify(self):
        current = discover_plex_storage(self.api, manual_source=self.plan.source)
        if (current.source, current.dataset, current.dataset_mount, current.relative_path) != (
                self.plan.source, self.plan.dataset, self.plan.dataset_mount, self.plan.relative_path):
            raise OperationDenied('Plex configuration storage changed after installation')
        mounts = tuple(self.mount_table())
        entries = [entry for entry in mounts if entry[0] == self.config]
        if entries != [(self.config, '/', 'zfs', self.plan.dataset)]:
            raise OperationDenied('Worker mount does not expose the exact Plex dataset root')
        snapshot_root = self.config/'.zfs'/'snapshot'
        for path, root, filesystem, source in mounts:
            if self.config in path.parents:
                snapshot = path.parent == snapshot_root and source == f'{self.plan.dataset}@{path.name}'
                if not snapshot or root != '/' or filesystem != 'zfs':
                    raise OperationDenied('Plex configuration contains a separate mounted filesystem')
        for path in (self.state, self.archives, self.archives/'Logs'):
            containing = [entry for entry in mounts if entry[0] == path or entry[0] in path.parents]
            if containing and max(containing, key=lambda entry: len(entry[0].parts))[3] == self.plan.dataset:
                raise OperationDenied('Worker state or archives use the Plex configuration dataset')
        if any(_directory_identity(path) != identity for path, identity in self._identities.items()):
            raise OperationDenied('Execution directory identity changed')


class ScopedExecutionAPI:
    """Restrict worker snapshot calls to its currently recorded snapshot."""
    def __init__(self, api, storage, store):
        self.api, self.storage, self.store = api, storage, store
        self.scope = Snapshots(None, None, storage.plan.dataset)

    def call(self, method, *params):
        if method == 'app.query':
            return self.api.call(method, [['name', '=', 'plex']], {'select': ['name', 'state']})
        if method not in {'pool.snapshot.query', 'pool.snapshot.create', 'pool.snapshot.delete', 'pool.snapshot.rollback'}:
            raise OperationDenied('API method is outside the execution scope')
        with self.store.transaction() as operation:
            identifier, kind = operation.snapshot_id, operation.kind
        self.scope._check(identifier)
        if method == 'pool.snapshot.query':
            expected = ([['id', '=', identifier]],)
        elif method == 'pool.snapshot.create':
            dataset, name = identifier.rsplit('@', 1)
            expected = ({'dataset': dataset, 'name': name, 'recursive': False},)
        elif method == 'pool.snapshot.delete':
            expected = (identifier, {'defer': False, 'recursive': False})
        elif method == 'pool.snapshot.rollback' and kind == 'RESTORE':
            expected = (identifier, dict.fromkeys(
                ('recursive', 'recursive_clones', 'force', 'recursive_rollback'), False))
        else:
            raise OperationDenied('API method is outside the execution scope')
        if params != expected:
            raise OperationDenied('Snapshot request is outside the execution scope')
        if method != 'pool.snapshot.query':
            self.storage.verify()
        return self.api.call(method, *expected)


def build_execution_worker(storage, *, sqlite_executable, sqlite_version):
    """Compose coordinators without mounting host storage or enabling WWW routes."""
    storage.verify()
    store, history, progress = StateStore(storage.state), History(storage.state), Progress(storage.state)
    api = ScopedExecutionAPI(storage.api, storage, store)
    dataset = storage.plan.dataset
    reader = SnapshotReader(storage.config, dataset, *storage.config_identity, api)
    database_check = PlexDatabaseChecker(sqlite_executable, sqlite_version)

    def backup():
        storage.verify()
        return Backup(api, store, history, progress, storage.state, storage.archives, dataset, reader)

    def restore():
        storage.verify()
        writer = ConfigWriter(storage.config, *storage.config_identity, PlexStatus(api))

        def write(staged):
            storage.verify()
            writer.write(staged)

        return Restore(api, store, history, progress, storage.state, storage.archives, dataset,
                       database_check, write, writer.verify, RollbackVerifier(store, reader, writer))

    return ExecutionWorker(storage.state, storage.archives, dataset, api, backup, restore)
