import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from plexconfigcontrol.operations import OperationDenied
from plexconfigcontrol.plex_storage import PlexStorage
from plexconfigcontrol.production_execution import ExecutionStorage, build_execution_worker
from plexconfigcontrol.snapshots import SnapshotError


class ProductionExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.config, self.state, self.archives = [root/name for name in ('config', 'state', 'archives')]
        for path in (self.config, self.state, self.archives/'Logs'):
            path.mkdir(parents=True)
        self.source = '/mnt/MediaPool/PlexConfig'
        self.dataset = 'MediaPool/PlexConfig'
        self.app_state = 'RUNNING'
        self.mount_entries = [(self.config, '/', 'zfs', self.dataset)]
        self.api = Mock()
        self.api.call.side_effect = self.call
        self.plan = PlexStorage('host_path', self.source, self.dataset, self.source, '.')

    def call(self, method, *params):
        if method == 'app.query':
            return [{'name': 'plex', 'state': self.app_state, 'active_workloads': {'volumes': [
                {'source': self.source, 'destination': '/config', 'type': 'bind'},
            ]}}]
        if method == 'filesystem.statfs':
            return {'source': self.dataset, 'dest': self.source, 'fstype': 'zfs'}
        if method == 'pool.snapshot.query':
            return []
        if method in ('pool.snapshot.create', 'pool.snapshot.delete', 'pool.snapshot.rollback'):
            return True
        self.fail(f'Unexpected host call: {method}')

    def storage(self):
        return ExecutionStorage(self.api, self.plan, self.config, self.state, self.archives,
                                mount_table=lambda: iter(self.mount_entries))

    def worker(self):
        worker = build_execution_worker(self.storage(), sqlite_executable='/fixed/plex-sqlite',
                                        sqlite_version='3.45.0')
        self.addCleanup(worker.close)
        return worker

    def test_configuration_is_bound_to_dataset_root_and_pinned_directories(self):
        storage = self.storage()
        self.mount_entries = [(self.config, '/subdir', 'zfs', self.dataset)]
        with self.assertRaisesRegex(OperationDenied, 'exact Plex dataset root'):
            storage.verify()
        self.mount_entries = [(self.config, '/', 'zfs', self.dataset),
                              (self.config/'nested', '/', 'zfs', 'MediaPool/Other')]
        with self.assertRaisesRegex(OperationDenied, 'separate mounted filesystem'):
            storage.verify()
        self.mount_entries = [(self.config, '/', 'zfs', self.dataset),
                              (self.archives, '/nested', 'zfs', self.dataset)]
        with self.assertRaisesRegex(OperationDenied, 'use the Plex configuration dataset'):
            storage.verify()
        self.mount_entries = [(self.config, '/', 'zfs', self.dataset)]
        self.archives.rename(self.archives.with_name('old-archives'))
        (self.archives/'Logs').mkdir(parents=True)
        with self.assertRaisesRegex(OperationDenied, 'identity changed'):
            storage.verify()

    def test_snapshot_calls_require_exact_current_intent_and_recheck_host_storage(self):
        worker = self.worker()
        snapshot_name = 'pcc-backup-' + 'a'*32
        identifier = self.dataset + '@' + snapshot_name
        with self.assertRaises(SnapshotError):
            worker.api.call('pool.snapshot.query', [['id', '=', identifier]])
        with worker.store.transaction() as operation:
            operation.begin('BACKUP')
            operation.begin_backup()
            operation.record_snapshot_intent(self.dataset, snapshot_name)
        with self.assertRaises(OperationDenied):
            worker.api.call('pool.snapshot.delete', identifier, {'defer': False, 'recursive': True})
        with self.assertRaises(OperationDenied):
            worker.api.call('pool.snapshot.rollback', identifier, {})
        request = {'dataset': self.dataset, 'name': snapshot_name, 'recursive': False}
        self.assertTrue(worker.api.call('pool.snapshot.create', request))
        self.dataset = 'Different/PlexConfig'
        with self.assertRaisesRegex(OperationDenied, 'changed after installation'):
            worker.api.call('pool.snapshot.create', request)
        mutations = [call for call in self.api.call.call_args_list if call.args[0] == 'pool.snapshot.create']
        self.assertEqual(len(mutations), 1)


if __name__ == '__main__':
    unittest.main()
