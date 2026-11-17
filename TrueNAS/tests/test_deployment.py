import unittest
from dataclasses import replace

from plexconfigcontrol.deployment import Deployment


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.deployment = Deployment(
            panel_image='plexconfigcontrol:local', worker_image='plexconfigcontrol-worker:local',
            state='/mnt/.ix-apps/app_mounts/plexconfigcontrol/state',
            archives='/mnt/ArchivePool/Family/Plex Config',
            plex_config='/mnt/MediaPool/Applications/Plex',
            plex_dataset='MediaPool/Applications/Plex',
            api_url='wss://nas.example/api/current', api_user='plexconfigcontrol',
            api_key_file='/mnt/PrivatePool/PCC/key', api_ca_file='/mnt/PrivatePool/PCC/ca.pem',
            verifier_file='/mnt/PrivatePool/PCC/verifier',
            host_ip='192.168.1.120', host_port=8787, sqlite_version='3.53.3',
        )

    def test_one_app_keeps_configuration_and_worker_secrets_out_of_panel(self):
        panel, worker = (self.deployment.compose()['services'][name] for name in ('panel', 'worker'))
        self.assertEqual(panel['ports'][0]['published'], '8787')
        self.assertNotIn('ports', worker)
        self.assertEqual(panel['volumes'][0], worker['volumes'][0])
        self.assertTrue(panel['volumes'][1]['read_only'])
        self.assertFalse(worker['volumes'][1]['read_only'])
        self.assertNotIn('cap_add', panel)
        self.assertNotIn(self.deployment.api_key_file, str(panel))
        self.assertNotIn(self.deployment.plex_config, str(panel))
        self.assertNotIn(self.deployment.verifier_file, str(worker))
        self.assertEqual(worker['volumes'][2]['bind']['propagation'], 'rslave')
        self.assertTrue(all(not v['bind']['create_host_path'] for service in (panel, worker)
                            for v in service['volumes']))
        self.assertEqual(worker['command'][worker['command'].index('--sqlite-version')+1], '3.53.3')

    def test_rejects_unsafe_paths_or_interpolated_values(self):
        for kwargs in (
                {'archives': self.deployment.plex_config+'/copies'},
                {'state': '/mnt/TrueNAS/TrueNAS/PBS-Data/app'},
                {'archives': '/mnt/ArchivePool/../Plex'},
                {'archives': '/mnt/ArchivePool/${UNTRUSTED}'},
                {'api_url': 'ws://nas.example/api/current'},
                {'api_user': '$INJECTED'},
                {'host_ip': '0.0.0.0'},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(self.deployment, **kwargs)


if __name__ == '__main__':
    unittest.main()
