import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from plexconfigcontrol.host_install import APP, InstallError, LocalMiddleware, form_settings, prepare, prepare_compose, require_truenas_version
from plexconfigcontrol.installation_storage import InstallationStoragePlan
from plexconfigcontrol.naming import Naming
from plexconfigcontrol.plex_storage import PlexStorage
from plexconfigcontrol.storage import create_destination


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
            {'fstype': 'zfs', 'source': 'ArchivePool/Family', 'dest': '/mnt/ArchivePool/Family'},
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
                         ['system.version', 'app.query', 'filesystem.statfs', 'docker.config', 'app.ix_volume.query', 'filesystem.statfs'])

    def test_local_middleware_rejects_mutating_methods(self):
        runner = Mock(return_value=SimpleNamespace(stdout='"TrueNAS-25.10.8"'))
        api = LocalMiddleware(runner)
        self.assertEqual(api.call('system.version'), 'TrueNAS-25.10.8')
        with self.assertRaises(InstallError):
            api.call('pool.dataset.create', {})
        runner.assert_called_once()

    def test_local_middleware_accepts_the_unquoted_truenas_version(self):
        runner = Mock(return_value=SimpleNamespace(stdout='TrueNAS-25.10.8\n'))
        api = LocalMiddleware(runner)
        self.assertEqual(api.call('system.version'), 'TrueNAS-25.10.8')
        with self.assertRaises(InstallError):
            api.call('docker.config')

    def test_stable_release_floor(self):
        for version in ('TrueNAS-25.10.8', 'TrueNAS-25.10.10', 'TrueNAS-26.0.0'):
            require_truenas_version(version)
        for version in ('TrueNAS-25.10.7', 'TrueNAS-26.0.0-BETA.1', 'Linux', None):
            with self.assertRaises(InstallError):
                require_truenas_version(version)

    def test_final_configuration_sends_a_structured_object_to_middleware(self):
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        compose = {'services': {'init': {'entrypoint': ['/bin/sh', '-ec', 'echo "$$1"\n' * 600]}}}
        with patch.dict('sys.modules', {'truenas_api_client': SimpleNamespace(Client=lambda: client)}):
            LocalMiddleware().configure(compose)
        client.call.assert_called_once_with('app.update', APP, {'custom_compose_config': compose}, job=True)

    def test_confirmed_preparation_creates_custom_folder_and_never_reuses_the_volume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root/'state'
            state.mkdir()
            plan = InstallationStoragePlan(str(root), PlexStorage(
                'host_path', '/mnt/MediaPool/Plex', 'MediaPool/Plex', '/mnt/MediaPool/Plex', '.'),
                Naming('Moje kopie Plex', 'PlexDom'))
            output = root/plan.naming.folder_name
            deployment = Mock(state=str(state), archives=str(output))
            deployment.compose.return_value = {'services': {'panel': {}}}
            expected = (deployment, plan, ('ArchivePool/Family', '/mnt/ArchivePool/Family'))
            with patch('plexconfigcontrol.host_install._prepare', return_value=expected),                  patch('plexconfigcontrol.host_install.os.geteuid', return_value=0),                  patch('plexconfigcontrol.host_install.os.chown'),                  patch('plexconfigcontrol.host_install.os.fchown'),                  patch('plexconfigcontrol.host_install._zfs', return_value=expected[2]),                  patch('plexconfigcontrol.host_install.create_storage',
                       side_effect=lambda _, current: create_destination(
                           current.parent, folder_name=current.naming.folder_name)) as create:
                with self.assertRaises(InstallError):
                    prepare_compose(Mock(), {}, expected)
                self.assertEqual(list(state.iterdir()), [])
                with self.assertRaisesRegex(InstallError, 'changed after review'):
                    prepare_compose(Mock(), {}, (deployment, None, expected[2]), confirmed=True)
                self.assertEqual(prepare_compose(Mock(), {}, expected, confirmed=True),
                                 {'services': {'panel': {}}})
                self.assertTrue((output/'Logs').is_dir())
                self.assertEqual(json.loads((state/'output-naming.json').read_text()),
                                 {'folder_name': 'Moje kopie Plex', 'archive_prefix': 'PlexDom'})
                with self.assertRaisesRegex(InstallError, 'already in use'):
                    prepare_compose(Mock(), {}, expected, confirmed=True)
                create.assert_called_once()

    def test_installer_keeps_the_managed_volume_and_waits_for_operational_health(self):
        from plexconfigcontrol.host_install import install_app
        api = Mock()
        deployment = Mock(host_ip='192.168.1.120', host_port=8787)
        reviewed = (deployment, Mock(), ('ArchivePool/Family', '/mnt/ArchivePool/Family'))
        api.allocate_state.return_value = {'name': APP, 'custom_app': False}
        api.convert.return_value = {'name': APP, 'custom_app': True}
        api.configure.return_value = {'name': APP, 'custom_app': True, 'state': 'STOPPED'}
        compose = {'services': {'panel': {}, 'worker': {}}}
        with patch('plexconfigcontrol.host_install._prepare', return_value=reviewed), \
             patch('plexconfigcontrol.host_install.os.geteuid', return_value=0), \
             patch('plexconfigcontrol.host_install.prepare_compose', return_value=compose) as prepare, \
             patch('plexconfigcontrol.host_install._ready') as ready:
            with self.assertRaises(InstallError):
                install_app(api, {}, reviewed)
            api.allocate_state.assert_not_called()
            self.assertEqual(install_app(api, {}, reviewed, confirmed=True),
                             {'app': APP, 'host_ip': '192.168.1.120', 'port': 8787})
            prepare.assert_called_once_with(api, {}, reviewed, confirmed=True)
            ready.assert_called_once_with(deployment)
        self.assertEqual([call[0] for call in api.method_calls],
                         ['allocate_state', 'convert', 'configure', 'start'])

    def test_built_in_allocation_targets_only_the_application_state(self):
        runner = Mock(return_value=SimpleNamespace(stdout='{}'))
        api = LocalMiddleware(runner)
        api.allocate_state(Mock(panel_image='plexconfigcontrol:local'))
        args = runner.call_args.args[0]
        self.assertEqual(args[:4], ['midclt', 'call', '--job', 'app.create'])
        definition = json.loads(args[4])
        self.assertEqual(definition['app_name'], APP)
        self.assertEqual(definition['catalog_app'], 'ix-app')
        self.assertNotIn('ports', definition['values'])
        self.assertEqual(definition['values']['storage'], [{
            'type': 'ix_volume', 'read_only': False, 'mount_path': '/var/lib/plexconfigcontrol',
            'ix_volume_config': {'dataset_name': 'state', 'acl_enable': False},
        }])

    def test_install_uses_isolated_sqlite_cache_with_unbundled_worker(self):
        from plexconfigcontrol.host_install import install_app
        reference = 'plexinc/pms-docker@sha256:' + 'a' * 64
        api = Mock()
        deployment = Mock(host_ip='192.168.1.120', host_port=8787, sqlite_version='3.53.3')
        deployment.compose.return_value = {'services': {
            'panel': {'volumes': []}, 'worker': {'volumes': []},
        }}
        reviewed = (deployment, Mock(), ('ArchivePool/Family', '/mnt/ArchivePool/Family'))
        api.allocate_state.return_value = {'name': APP, 'custom_app': False}
        api.convert.return_value = {'name': APP, 'custom_app': True}
        api.configure.return_value = {'name': APP, 'custom_app': True, 'state': 'RUNNING'}
        with patch('plexconfigcontrol.host_install._prepare', return_value=reviewed), \
             patch('plexconfigcontrol.host_install.os.geteuid', return_value=0), \
             patch('plexconfigcontrol.host_install.prepare_compose'), \
             patch('plexconfigcontrol.host_install._ready'):
            install_app(api, {}, reviewed, confirmed=True, plex_reference=reference)
        compose, = api.configure.call_args.args
        self.assertEqual(compose['services']['initialize-plex-sqlite']['image'], reference)
        self.assertTrue(compose['services']['worker']['volumes'][-1]['read_only'])
        self.assertEqual(compose['services']['panel']['volumes'], [])

    def test_managed_install_requests_an_additional_private_ixvolume(self):
        runner = Mock(return_value=SimpleNamespace(stdout='{}'))
        LocalMiddleware(runner).allocate_state(Mock(panel_image='plexconfigcontrol:local'), managed_private=True)
        definition = json.loads(runner.call_args.args[0][4])
        self.assertEqual([volume['ix_volume_config']['dataset_name'] for volume in definition['values']['storage']],
                         ['state', 'pcc'])

    def test_managed_private_files_store_only_final_paths(self):
        from plexconfigcontrol.host_install import PRIVATE_FILES, _store_managed_private
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / 'pcc'
            private.mkdir()
            values = {'panel': {}, 'connection': {}, 'backup': {}, 'plex': {}}
            deployment = Mock(state=str(root / 'state'))
            for field, (filename, _, _) in PRIVATE_FILES.items():
                source = root / filename
                source.write_text(field)
                values['panel' if field == 'verifier_file' else 'connection'][field] = str(source)
                setattr(deployment, field, str(private / filename))
            api = Mock()
            api.call.return_value = {'dataset': 'pool/ix-apps'}
            lstat = Path.lstat

            def verified_stat(path):
                if path == private:
                    return SimpleNamespace(st_mode=lstat(path).st_mode, st_uid=0)
                return lstat(path)

            with patch('plexconfigcontrol.host_install._zfs', return_value=(
                    f'pool/ix-apps/app_mounts/{APP}/pcc', str(private))), \
                 patch.object(Path, 'lstat', verified_stat), \
                 patch('plexconfigcontrol.host_install._verify_private_file'), \
                 patch('plexconfigcontrol.host_install.os.fchown'):
                _store_managed_private(api, deployment, values)
            stored = json.loads((private / 'settings.json').read_text())
            for field, (filename, _, mode) in PRIVATE_FILES.items():
                path = private / filename
                self.assertEqual(path.read_text(), field)
                self.assertEqual(path.stat().st_mode & 0o777, mode)
                self.assertEqual(stored['panel' if field == 'verifier_file' else 'connection'][field], str(path))
            self.assertEqual(private.stat().st_mode & 0o777, 0o700)
