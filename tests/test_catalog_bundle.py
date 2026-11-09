import json
import unittest
from pathlib import Path

from plexconfigcontrol.catalog_bundle import catalog_files
from plexconfigcontrol.deployment import Deployment
from plexconfigcontrol.installation_storage import InstallationStoragePlan
from plexconfigcontrol.naming import Naming
from plexconfigcontrol.plex_storage import PlexStorage

try:
    from jinja2 import Environment, StrictUndefined, UndefinedError
except ImportError:
    Environment = None


class CatalogBundleTests(unittest.TestCase):
    def setUp(self):
        source = '/mnt/.ix-apps/app_mounts/plex/config'
        dataset = 'AppPool/ix-apps/app_mounts/plex/config'
        self.state = '/mnt/.ix-apps/app_mounts/plexconfigcontrol/state'
        self.archives = '/mnt/ArchivePool/Family/Moje kopie Plex'
        self.deployment = Deployment(
            panel_image='plexconfigcontrol:local', worker_image='plexconfigcontrol-worker:local',
            state=self.state, archives=self.archives, plex_config=source, plex_dataset=dataset,
            api_url='wss://192.168.1.120/api/current', api_user='pcc',
            api_key_file='/mnt/Private/PCC/key', api_ca_file='/mnt/Private/PCC/ca',
            verifier_file='/mnt/Private/PCC/verifier', host_ip='192.168.1.120',
            host_port=8787, sqlite_version='3.53.3',
        )
        self.plan = InstallationStoragePlan('/mnt/ArchivePool/Family',
            PlexStorage('ix_volume', source, dataset, source, '.'), Naming('Moje kopie Plex', 'PlexDom'))
        self.values = {
            'panel': {'host_ip': '192.168.1.120', 'host_port': 8787,
                      'verifier_file': self.deployment.verifier_file},
            'backup': {'archive_parent': self.plan.parent, 'folder_name': 'Moje kopie Plex',
                       'archive_prefix': 'PlexDom'},
            'connection': {'api_user': 'pcc', 'api_key_file': self.deployment.api_key_file,
                           'api_ca_file': self.deployment.api_ca_file, 'api_url': ''},
            'plex': {'storage_mode': 'automatic'},
        }
        root = Path(__file__).resolve().parents[1]/'design/truenas-installation'
        self.files = catalog_files(root, self.deployment, self.plan, self.values, '0.1.0')

    def test_prepared_folder_and_state_dependencies_are_bound(self):
        release = json.loads(self.files['ix_values.yaml'])['pcc_release']
        panel, worker, initialize = (release['compose']['services'][name]
                                      for name in ('panel', 'worker', 'initialize-state'))
        self.assertEqual(panel['volumes'][1]['source'], self.archives)
        self.assertEqual(worker['volumes'][1]['source'], self.archives)
        self.assertEqual(initialize['volumes'], [panel['volumes'][0]])
        self.assertEqual(initialize['network_mode'], 'none')
        self.assertEqual(initialize['command'], ['--folder', 'Moje kopie Plex', '--prefix', 'PlexDom'])
        for service in (panel, worker):
            self.assertEqual(service['depends_on']['initialize-state']['condition'],
                             'service_completed_successfully')
        form = json.loads(self.files['questions.yaml'])
        backup = next(q['schema'] for q in form['questions'] if q['variable'] == 'backup')
        name = next(f['schema'] for f in backup['attrs'] if f['variable'] == 'folder_name')
        self.assertEqual(name['default'], 'Moje kopie Plex')

    @unittest.skipIf(Environment is None, 'Jinja is used by the catalog renderer')
    def test_render_rejects_changes_and_wrong_ixvolume(self):
        template = Environment(undefined=StrictUndefined).from_string(self.files['templates/docker-compose.yaml'])
        data = {**self.values, **json.loads(self.files['ix_values.yaml']),
                'ix_context': {'app_name': 'plexconfigcontrol'}, 'ix_volumes': {'state': self.state}}
        actual = json.loads(template.render(values=data))
        self.assertEqual(actual['services']['panel']['volumes'][1]['source'], self.archives)
        with self.assertRaisesRegex(UndefinedError, 'ustawienia zmieniono'):
            template.render(values={**data, 'backup': {**data['backup'], 'folder_name': 'Inna nazwa'}})
        with self.assertRaisesRegex(UndefinedError, 'iXVolume'):
            template.render(values={**data, 'ix_volumes': {'state': '/mnt/Another/state'}})
        with self.assertRaisesRegex(UndefinedError, 'ustawienia zmieniono'):
            template.render(values={**data, 'connection': {**data['connection'],
                            'api_key_file': '/mnt/Another/key'}})

    @unittest.skipIf(Environment is None, 'Jinja is used by the catalog renderer')
    def test_render_applies_form_port_and_prefix_without_changing_host_mounts(self):
        template = Environment(undefined=StrictUndefined).from_string(self.files['templates/docker-compose.yaml'])
        data = {**self.values, **json.loads(self.files['ix_values.yaml']),
                'ix_context': {'app_name': 'plexconfigcontrol'}, 'ix_volumes': {'state': self.state}}
        data['panel'] = {**data['panel'], 'host_port': 9443}
        data['backup'] = {**data['backup'], 'archive_prefix': 'Plex-Dom_2'}
        services = json.loads(template.render(values=data))['services']
        self.assertEqual(services['panel']['ports'][0],
                         {'target': 8443, 'published': '9443', 'host_ip': self.deployment.host_ip,
                          'protocol': 'tcp'})
        self.assertEqual(services['initialize-state']['command'],
                         ['--folder', 'Moje kopie Plex', '--prefix', 'Plex-Dom_2'])
        expected = self.deployment.compose()['services']
        for service in ('panel', 'worker'):
            self.assertEqual(services[service]['volumes'], expected[service]['volumes'])
        for invalid in (True, '9443', 1023, 65536):
            with self.subTest(port=invalid), self.assertRaisesRegex(UndefinedError, 'wybierz port'):
                template.render(values={**data, 'panel': {**data['panel'], 'host_port': invalid}})
        for invalid in ('', '_bad', '../bad', 'Plex.2', 'Plex$VAR', 'Plex-ą', 'Plex\n', 'A' * 65):
            with self.subTest(prefix=invalid), self.assertRaisesRegex(UndefinedError, 'początek nazwy'):
                template.render(values={**data, 'backup': {**data['backup'], 'archive_prefix': invalid}})
