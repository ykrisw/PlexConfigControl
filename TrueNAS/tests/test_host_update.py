import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from plexconfigcontrol import host_update as update
from plexconfigcontrol.host_install import InstallError
from plexconfigcontrol.locking import operation_lock


class HostUpdateTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.state = folder / 'state'
        self.state.mkdir()
        self.record = folder / update.RECORD
        self.stack.enter_context(patch.object(update, 'STATE', self.state))
        self.compose = {'services': {
            'panel': {'image': 'plexconfigcontrol:old', 'volumes': [{'source': '/unchanged/state'}]},
            'worker': {'image': 'plexconfigcontrol-worker:old', 'command': ['--unchanged']},
            'initialize-plex-sqlite': {'image': 'plex@sha256:fixture', 'environment': {
                'PCC_SQLITE_VERSION': '3.53.3'}},
        }}
        self.old = copy.deepcopy(self.compose)
        self.endpoint = Mock()
        self.status = 'RUNNING'
        self.jobs = []
        self.api = Mock()
        self.api.call.side_effect = self.lookup
        self.api.stop.side_effect = lambda: self.set_status('STOPPED')
        self.api.start.side_effect = lambda: self.set_status('RUNNING')
        self.api.configure.side_effect = self.configure
        self.stack.enter_context(patch.object(update, '_zfs', side_effect=[
            ('pool/ix-apps', update.APPS_MOUNT),
            ('pool/ix-apps/app_mounts/plexconfigcontrol/state', str(self.state)),
        ]))
        self.stack.enter_context(patch.object(update, '_details', return_value=(self.record, self.endpoint)))
        self.stack.enter_context(patch.object(update, 'detect_plex_runtime',
                                            return_value=('plex@sha256:fixture', '3.53.3', 'id', 'image')))
        self.stack.enter_context(patch.object(update, '_inspect_images'))
        self.stack.enter_context(patch.object(update, '_check_running_images'))
        self.stack.enter_context(patch.object(update.subprocess, 'run'))
        self.stack.enter_context(patch('builtins.input', return_value='tak'))
        self.ready = self.stack.enter_context(patch.object(update, '_ready'))
        self.set_operation('IDLE')
        with sqlite3.connect(self.state / 'execution.sqlite3') as database:
            database.execute('CREATE TABLE requests (state TEXT)')

    def set_status(self, value):
        self.status = value

    def set_operation(self, phase):
        with sqlite3.connect(self.state / 'operations.sqlite3') as database:
            database.execute('CREATE TABLE IF NOT EXISTS operation (id INTEGER PRIMARY KEY, payload TEXT)')
            database.execute('INSERT OR REPLACE INTO operation VALUES (1, ?)',
                             (json.dumps({'phase': phase, 'snapshot_id': None}),))

    def lookup(self, method, *args):
        return {
            'system.version': 'TrueNAS-25.10.8',
            'docker.config': {'dataset': 'pool/ix-apps'},
            'app.query': [{'name': update.APP, 'custom_app': True, 'state': self.status}],
            'app.config': copy.deepcopy(self.compose),
            'core.get_jobs': self.jobs,
            'app.ix_volume.query': [{'app_name': update.APP, 'name': 'state'}],
        }[method]

    def configure(self, compose):
        self.assertEqual(self.status, 'STOPPED')
        self.compose = copy.deepcopy(compose)
        return {'name': update.APP, 'custom_app': True}

    def test_update_changes_only_images_and_clears_recovery_record(self):
        update._update(self.api)
        self.assertEqual(self.status, 'RUNNING')
        self.assertFalse(self.record.exists())
        for service in update.REPOSITORIES:
            self.assertIn(':update-', self.compose['services'][service]['image'])
            self.compose['services'][service]['image'] = self.old['services'][service]['image']
        self.assertEqual(self.compose, self.old)

    def test_failed_new_start_restores_original_configuration(self):
        self.ready.side_effect = [None, InstallError('unhealthy'), None]
        with self.assertRaisesRegex(InstallError, 'Poprzednia wersja działa'):
            update._update(self.api)
        self.assertEqual(self.compose, self.old)
        self.assertEqual(self.status, 'RUNNING')
        self.assertFalse(self.record.exists())

    def test_failed_rollback_retains_record_for_next_run(self):
        self.ready.side_effect = [None, InstallError('unhealthy'), InstallError('unhealthy')]
        with self.assertRaisesRegex(InstallError, 'Uruchom ponownie ten sam kreator'):
            update._update(self.api)
        self.assertEqual(json.loads(self.record.read_text())['previous'], self.old)
        self.assertEqual(self.record.stat().st_mode & 0o777, 0o600)

    def test_interrupted_update_reopens_previous_version(self):
        candidate = copy.deepcopy(self.old)
        candidate['services']['panel']['image'] = 'plexconfigcontrol:update-fixture'
        update._write_record(self.record, self.old, candidate)
        self.compose = candidate
        self.status = 'STOPPED'
        update._update(self.api)
        self.assertEqual(self.compose, self.old)
        self.assertEqual(self.status, 'RUNNING')
        self.assertFalse(self.record.exists())

    def test_operation_in_progress_blocks_update(self):
        with operation_lock(self.state), self.assertRaises(update.OperationBusy):
            update._update(self.api)
        self.api.stop.assert_not_called()
        self.api.configure.assert_not_called()

    def test_recovery_required_blocks_update(self):
        self.set_operation('RECOVERY_REQUIRED')
        with self.assertRaisesRegex(InstallError, 'odzyskiwanie'):
            update._update(self.api)
        self.api.stop.assert_not_called()
        self.api.configure.assert_not_called()

    def test_true_nas_job_for_this_app_blocks_update(self):
        self.jobs = [{'arguments': [update.APP]}]
        with self.assertRaisesRegex(InstallError, 'nadal wykonuje zadanie'):
            update._update(self.api)
        self.api.stop.assert_not_called()
        self.api.configure.assert_not_called()

    def test_check_only_does_not_build_stop_or_change_configuration(self):
        with patch('builtins.input') as prompt:
            update._update(self.api, check_only=True)
        prompt.assert_not_called()
        update.subprocess.run.assert_not_called()
        self.api.stop.assert_not_called()
        self.api.start.assert_not_called()
        self.api.configure.assert_not_called()
        self.assertFalse(self.record.exists())
