import subprocess
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
