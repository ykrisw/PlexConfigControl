import subprocess
import json
import tempfile
import unittest
from unittest.mock import Mock

from tests.host_snapshot_smoke import SandboxAPI


class HostAdapterTests(unittest.TestCase):
    def test_void_success_is_not_parsed_as_json_and_absence_is_queried_separately(self):
        runner = Mock(side_effect=[
            subprocess.CompletedProcess([], 0, '', ''),
            subprocess.CompletedProcess([], 0, '[]\n', ''),
        ])
        dataset = 'TrueNAS/pcc-test-'+'a'*32
        api = SandboxAPI(dataset, runner)
        self.assertIsNone(api.call('pool.dataset.delete', dataset,
                                  {'recursive': False, 'force': False}))
        self.assertEqual(api.call('pool.dataset.query', [['id', '=', dataset]]), [])
        self.assertEqual(runner.call_count, 2)

    def test_production_paths_stop_start_recursive_and_unowned_snapshots_never_execute(self):
        runner = Mock()
        dataset = 'TrueNAS/pcc-test-'+'a'*32
        api = SandboxAPI(dataset, runner)
        for method, args in (
            ('app.stop', ('plex',)),
            ('app.start', ('plex',)),
            ('pool.dataset.delete', ('TrueNAS/ix-apps/app_mounts/plex/config', {})),
            ('pool.dataset.delete', (dataset, {'recursive': True, 'force': False})),
            ('pool.snapshot.delete', (dataset+'@other', {'defer': False, 'recursive': False})),
            ('pool.snapshot.rollback', (dataset+'@other', {})),
            ('pool.snapshot.create', ({'dataset': 'TrueNAS/TrueNAS/PBS-Data',
                'name': 'pcc-backup-'+'b'*32, 'recursive': False},)),
        ):
            with self.subTest(method=method), self.assertRaises(ValueError):
                api.call(method, *args)
        runner.assert_not_called()

    def test_error_or_invalid_json_is_never_interpreted_as_absence(self):
        dataset = 'TrueNAS/pcc-test-'+'a'*32
        for result, error in (
            (subprocess.CompletedProcess([], 1, '', 'failed'), RuntimeError),
            (subprocess.CompletedProcess([], 0, 'invalid', ''), ValueError),
        ):
            api = SandboxAPI(dataset, Mock(return_value=result))
            with self.assertRaises(error):
                api.call('pool.dataset.query', [['id', '=', dataset]])

    def test_adapter_rejects_other_dataset_names(self):
        for dataset in ('TrueNAS', 'TrueNAS/TrueNAS/PBS-Data',
                        'TrueNAS/pcc-test-'+'a'*32+'/child'):
            with self.subTest(dataset=dataset), self.assertRaises(ValueError):
                SandboxAPI(dataset)

    def test_snapshot_remove_handles_python_scalar_then_confirms_absence(self):
        from plexconfigcontrol.state import StateStore
        from plexconfigcontrol.snapshots import Snapshots
        dataset = 'TrueNAS/pcc-test-'+'a'*32
        name = 'pcc-backup-'+'b'*32
        identifier = dataset+'@'+name
        for scalar in ('True\n', 'False\n', 'None\n', '', 'null\n'):
            with self.subTest(output=scalar), tempfile.TemporaryDirectory() as root:
                store = StateStore(root)
                with store.transaction() as operation:
                    operation.begin('BACKUP')
                    operation.begin_backup()
                    operation.record_snapshot_intent(dataset, name)
                runner = Mock(side_effect=[
                    subprocess.CompletedProcess([], 0, json.dumps([{'id':identifier}]), ''),
                    subprocess.CompletedProcess([], 0, scalar, ''),
                    subprocess.CompletedProcess([], 0, '[]', ''),
                ])
                api = SandboxAPI(dataset, runner)
                api.owned_snapshots.add(identifier)
                Snapshots(api, store, dataset).remove()
                with store.transaction() as operation:
                    self.assertIsNone(operation.snapshot_id)
                self.assertEqual(runner.call_count, 3)

    def test_successful_delete_output_does_not_clear_intent_if_query_still_finds_snapshot(self):
        from plexconfigcontrol.state import StateStore
        from plexconfigcontrol.snapshots import Snapshots, SnapshotError
        dataset = 'TrueNAS/pcc-test-'+'a'*32
        name = 'pcc-backup-'+'b'*32
        identifier = dataset+'@'+name
        with tempfile.TemporaryDirectory() as root:
            store = StateStore(root)
            with store.transaction() as operation:
                operation.begin('BACKUP')
                operation.begin_backup()
                operation.record_snapshot_intent(dataset, name)
            present = json.dumps([{'id':identifier}])
            runner = Mock(side_effect=[
                subprocess.CompletedProcess([], 0, present, ''),
                subprocess.CompletedProcess([], 0, 'True\n', ''),
                subprocess.CompletedProcess([], 0, present, ''),
            ])
            api = SandboxAPI(dataset, runner)
            api.owned_snapshots.add(identifier)
            with self.assertRaises(SnapshotError):
                Snapshots(api, store, dataset).remove()
            with store.transaction() as operation:
                self.assertEqual(operation.snapshot_id, identifier)

    def test_empty_or_python_scalar_query_is_not_a_json_absence_result(self):
        dataset = 'TrueNAS/pcc-test-'+'a'*32
        for output in ('', 'True\n', 'None\n'):
            with self.subTest(output=output):
                api = SandboxAPI(dataset, Mock(return_value=
                    subprocess.CompletedProcess([], 0, output, '')))
                with self.assertRaises(ValueError):
                    api.call('pool.dataset.query', [['id', '=', dataset]])
