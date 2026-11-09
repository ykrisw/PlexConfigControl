import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from plexconfigcontrol.host_install import APP, InstallError, LocalMiddleware, form_settings, prepare
from plexconfigcontrol.installation_storage import InstallationStoragePlan
from plexconfigcontrol.naming import Naming
from plexconfigcontrol.plex_storage import PlexStorage


class HostInstallTests(unittest.TestCase):
    def setUp(self):
        self.values = {
            'panel': {'host_ip': '192.168.1.120', 'host_port': 8787,
                      'verifier_file': '/mnt/Secrets/PCC/verifier'},
            'backup': {'archive_parent': '/mnt/ArchivePool/Family', 'folder_name': 'Plex Config',
                       'archive_prefix': 'PlexConfig'},
            'connection': {'api_user': 'pcc', 'api_key_file': '/mnt/Secrets/PCC/api-key',
                           'api_ca_file': '/mnt/Secrets/PCC/ca.pem'},
            'plex': {'storage_mode': 'automatic', 'manual_source': '/mnt/Ignore/HiddenField'},
        }

    def settings(self):
        return form_settings(self.values, panel_image='plexconfigcontrol:local',
                             worker_image='plexconfigcontrol-worker:local', sqlite_version='3.53.3')

    def test_form_defaults_keep_simple_path_and_validate_manual_mode(self):
        schema_path = Path(__file__).resolve().parents[1]/'design/truenas-installation/questions.yaml'
        form = json.loads(schema_path.read_text())
        questions = {item['variable']: item['schema'] for item in form['questions']}
        self.assertEqual(questions['state']['$ref'], ['normalize/ix_volume'])
        self.assertEqual(questions['state']['attrs'][0]['schema']['default'], 'state')
        for group, field in [('panel', 'host_port'), ('backup', 'folder_name'), ('backup', 'archive_prefix')]:
            fields = {item['variable']: item['schema'] for item in questions[group]['attrs']}
            self.assertEqual(self.values[group][field], fields[field]['default'])
        settings = self.settings()
        self.assertIsNone(settings['manual_source'])
        self.assertEqual(settings['api_url'], 'wss://192.168.1.120/api/current')
        self.values['plex']['storage_mode'] = 'manual'
        self.assertEqual(self.settings()['manual_source'], '/mnt/Ignore/HiddenField')
        self.values['plex'].pop('manual_source')
        with self.assertRaises(InstallError):
            self.settings()

    def test_preflight_resolves_storage_and_never_provisions_anything(self):
        api = Mock()
        api.call.side_effect = [
            'TrueNAS-25.10.8', [], {'fstype': 'zfs', 'source': 'OtherPool/ix-apps', 'dest': '/mnt/.ix-apps'},
            {'dataset': 'OtherPool/ix-apps'}, [],
        ]
        plan = InstallationStoragePlan('/mnt/ArchivePool/Family', PlexStorage(
            'host_path', '/mnt/MediaPool/Plex', 'MediaPool/Plex', '/mnt/MediaPool/Plex', '.'),
            Naming('Plex Config', 'PlexConfig'))
        with patch('plexconfigcontrol.host_install.plan_storage', return_value=plan), \
             patch('plexconfigcontrol.host_install._verify_private_file'), \
             patch('plexconfigcontrol.host_install._verify_local_images'):
            deployment = prepare(api, self.settings())
        self.assertEqual(deployment.state, f'/mnt/.ix-apps/app_mounts/{APP}/state')
        self.assertEqual(deployment.archives, '/mnt/ArchivePool/Family/Plex Config')
        self.assertEqual(deployment.plex_dataset, 'MediaPool/Plex')
        self.assertEqual([call.args[0] for call in api.call.call_args_list],
                         ['system.version', 'app.query', 'filesystem.statfs', 'docker.config', 'app.ix_volume.query'])

    def test_local_middleware_rejects_mutating_methods(self):
        runner = Mock(return_value=SimpleNamespace(stdout='"TrueNAS-25.10.8"'))
        api = LocalMiddleware(runner)
        self.assertEqual(api.call('system.version'), 'TrueNAS-25.10.8')
        with self.assertRaises(InstallError):
            api.call('pool.dataset.create', {})
        runner.assert_called_once()
