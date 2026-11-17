import ipaddress
import os
import runpy
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch
from zipfile import ZipFile

from deploy import build_self_extracting, install_pl


class GuidedInstallerTests(unittest.TestCase):
    def test_reset_removes_recognized_preparation_and_preserves_ca(self):
        records = {
            'user.query': {'id': 10, 'full_name': 'PlexConfigControl', 'builtin': False, 'smb': False,
                           'password_disabled': True, 'shell': '/usr/sbin/nologin', 'home': '/var/empty'},
            'group.query': {'id': 20, 'gid': 3000, 'builtin': False, 'smb': False, 'users': [10]},
            'privilege.query': {'id': 30, 'builtin_name': None, 'ds_groups': [],
                                'local_groups': [{'gid': 3000}], 'roles': install_pl.ROLES, 'web_shell': False},
            'api_key.query': {'id': 40, 'username': install_pl.APP},
        }
        client = Mock()
        client.call.side_effect = [[], [], *([row] for row in records.values()), [{'id': 40}], True, True, 10, 20]
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            files = [private / name for name in install_pl.PREPARATION_FILES]
            for path in files:
                path.touch(mode=0o600)
            certificate = private / 'truenas-ca.pem'
            certificate.touch()
            with patch.object(install_pl, 'private_directory'), patch.object(Path, 'lstat') as info:
                info.return_value = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=568)
                install_pl.reset_previous_preparation(client, private, files, records)
            self.assertTrue(certificate.exists())
            self.assertFalse(any(path.exists() for path in files))
        self.assertEqual(client.call.call_args_list[-4:], [
            call('api_key.delete', 40), call('privilege.delete', 30),
            call('user.delete', 10, {'delete_group': False}),
            call('group.delete', 20, {'delete_users': False}),
        ])

    def test_reset_refuses_an_existing_app_or_volume(self):
        for responses in ([[{'name': install_pl.APP}]], [[], [{'name': 'state'}]]):
            with self.subTest(responses=responses):
                client = Mock()
                client.call.side_effect = responses
                with patch.object(install_pl, 'previous_preparation') as previous:
                    with self.assertRaises(ValueError):
                        install_pl.reset_previous_preparation(client, Path('/mnt/Pool/PCC-Private'), [], {})
                previous.assert_not_called()

    def test_reset_refuses_a_key_owned_by_another_account(self):
        client = Mock()
        records = {'api_key.query': {'id': 40, 'username': 'admin'}}
        client.call.side_effect = [[], [], [], [], [], [records['api_key.query']]]
        with patch.object(install_pl, 'private_directory'):
            with self.assertRaisesRegex(ValueError, 'innego konta'):
                install_pl.reset_previous_preparation(client, Path('/mnt/Pool/PCC-Private'), [], records)
        self.assertTrue(all(entry.args[0].endswith('.query') for entry in client.call.call_args_list))

    def test_old_preparation_requires_explicit_reset_confirmation(self):
        private = Path('/mnt/Pool/PCC-Private')
        client = Mock()
        with patch.object(install_pl, 'preflight', return_value=({}, 'pem')), \
             patch.object(install_pl, 'previous_preparation', return_value=([private / 'settings.json'], {})), \
             patch.object(install_pl, 'ask_password_verifier', return_value='verifier'), \
             patch.object(install_pl, 'reset_previous_preparation') as reset, \
             patch('builtins.input', return_value='tak'):
            with self.assertRaisesRegex(ValueError, 'anulowane'):
                install_pl.settings(client, SimpleNamespace(krok='instaluj'), private)
        reset.assert_not_called()
        client.call.assert_not_called()

    def test_ipv4_menu_only_suggests_valid_non_loopback_addresses(self):
        client = Mock()
        client.call.return_value = [
            {'type': 'INET', 'address': '127.0.0.1'},
            {'type': 'INET', 'address': '192.168.10.120'},
            {'type': 'INET', 'address': '192.168.1.120'},
            {'type': 'INET', 'address': '192.168.1.120'},
            {'type': 'INET', 'address': '0.0.0.0'},
            {'type': 'INET6', 'address': '::1'},
        ]
        addresses = install_pl.local_ipv4_addresses(client)
        self.assertEqual(addresses, [ipaddress.IPv4Address('192.168.1.120'),
                                     ipaddress.IPv4Address('192.168.10.120')])
        with patch('builtins.input', side_effect=['3', '2']):
            self.assertEqual(install_pl.ask_ipv4_address(addresses), addresses[1])
        with patch('builtins.input', return_value=''):
            self.assertEqual(install_pl.ask_ipv4_address(addresses[:1]), addresses[0])
        with patch('builtins.input', return_value='10.0.0.1'):
            self.assertEqual(install_pl.ask_ipv4_address([]), ipaddress.IPv4Address('10.0.0.1'))

    def test_panel_port_prompt_retries_invalid_values_and_accepts_default(self):
        with patch('builtins.input', side_effect=['a', '443', '65536', '']), \
             patch.object(install_pl, 'panel_port_available', return_value=True) as available:
            self.assertEqual(install_pl.ask_panel_port('192.168.1.120'), 8787)
        available.assert_called_once_with('192.168.1.120', 8787)

    def test_occupied_panel_port_suggests_the_next_available_port(self):
        with patch('builtins.input', side_effect=['', '']) as prompt, \
             patch.object(install_pl, 'panel_port_available', side_effect=[False, False, True, True]):
            self.assertEqual(install_pl.ask_panel_port('192.168.1.120'), 8789)
        self.assertIn('[8789]', prompt.call_args.args[0])

    def test_password_prompt_retries_mismatch_before_generating_verifier(self):
        with patch.object(install_pl.getpass, 'getpass', side_effect=['', 'one', 'two', 'secret', 'secret']), \
             patch.object(install_pl, 'password_verifier', return_value='verifier') as verifier:
            self.assertEqual(install_pl.ask_password_verifier(), 'verifier')
        verifier.assert_called_once_with('secret')

    def test_single_file_launcher_removes_extracted_files_on_success_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'installer.zip'
            launcher = root / 'PlexConfigControl Instalator.py'
            with ZipFile(source, 'w') as archive:
                archive.writestr(build_self_extracting.ENTRY_POINT, '#!/bin/sh\n')
            build_self_extracting.build(source, launcher)
            main = runpy.run_path(str(launcher))['main']

            for exit_status in (0, 1):
                with self.subTest(exit_status=exit_status):
                    def launch(command, *, env):
                        self.assertEqual(command[0], 'sh')
                        self.assertEqual(command[2:], ['sprawdz'])
                        self.assertTrue(Path(command[1]).is_file())
                        self.assertEqual(env['PCC_INSTALLER_FILE'], str(launcher.resolve()))
                        return exit_status

                    with patch('os.geteuid', return_value=0), patch('subprocess.call', side_effect=launch) as call, \
                         patch.object(sys, 'argv', [str(launcher), 'sprawdz']):
                        self.assertEqual(main(), exit_status)
                    extracted = Path(call.call_args.args[0][1]).parents[1]
                    self.assertFalse(extracted.exists())

    def test_resume_command_uses_the_original_single_file_installer(self):
        with patch.dict(os.environ, {'PCC_INSTALLER_FILE': '/mnt/pool/Setup File.py'}):
            self.assertEqual(install_pl.resume_command('/mnt/pool/PCC-Private/settings.json'),
                             "sudo python3 '/mnt/pool/Setup File.py' --wznow /mnt/pool/PCC-Private/settings.json")

    def test_dataset_menu_excludes_apps_unmounted_and_readonly_datasets(self):
        client = Mock()
        client.call.side_effect = [{'dataset': 'Pool/ix-apps'}, [
            {'id': 'Pool/ix-apps/config', 'mountpoint': '/mnt/.ix-apps/config'},
            {'id': 'Other/hidden', 'mountpoint': '/mnt/Other/.hidden'},
            {'id': 'Other/locked', 'mountpoint': None},
            {'id': 'Other/unmounted', 'mountpoint': '/mnt/Other/unmounted'},
            {'id': 'Other/readonly', 'mountpoint': '/mnt/Other/readonly', 'readonly': {'value': 'on'}},
            {'id': 'Other/backup', 'mountpoint': '/mnt/Other/backup'},
            {'id': 'ArchivePool/family', 'mountpoint': '/mnt/ArchivePool/family'},
        ]]
        with patch.object(Path, 'is_mount', autospec=True,
                          side_effect=lambda path: path.name != 'unmounted'):
            choices = install_pl.available_archive_datasets(client)
        self.assertEqual(choices, [('ArchivePool/family', Path('/mnt/ArchivePool/family')),
                                   ('Other/backup', Path('/mnt/Other/backup'))])
        with patch('builtins.input', side_effect=['3', '2']):
            self.assertEqual(install_pl.ask_archive_parent(choices), Path('/mnt/Other/backup'))

    def test_folder_prompt_preserves_name_and_retries_when_taken(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            (parent / 'Plex Config').mkdir()
            with patch('builtins.input', side_effect=['Plex Config', 'Baza Danych Plex - Auto']):
                self.assertEqual(install_pl.ask_archive_folder(parent), 'Baza Danych Plex - Auto')

    def test_folder_prompt_suggests_a_free_name_without_reusing_existing_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            (parent / 'Plex Config').mkdir()
            (parent / 'Plex Config 2').mkdir()
            with patch('builtins.input', return_value='') as prompt:
                self.assertEqual(install_pl.ask_archive_folder(parent), 'Plex Config 3')
            self.assertIn('[Plex Config 3]', prompt.call_args.args[0])
            self.assertFalse((parent / 'Plex Config 3').exists())

    def test_dataset_prompt_accepts_true_nas_dataset_names_and_retries_invalid_paths(self):
        with patch('builtins.input', side_effect=['/home/copied-by-mistake', 'ArchivePool/Family']) as prompt:
            self.assertEqual(install_pl.ask_archive_parent(), Path('/mnt/ArchivePool/Family'))
        self.assertEqual(prompt.call_count, 2)
        self.assertEqual(install_pl.archive_parent('/mnt/ArchivePool/Family'), Path('/mnt/ArchivePool/Family'))
        with self.assertRaises(ValueError):
            install_pl.archive_parent('ArchivePool/../Family')

    def test_previous_preparation_lists_artifacts_without_reading_their_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            (private / 'truenas-key').write_text('secret contents')
            client = Mock()
            client.call.side_effect = [[{'id': 1}], [], [], []]
            with self.assertRaises(ValueError) as raised:
                install_pl.check_previous_preparation(client, private)
        message = str(raised.exception)
        self.assertIn('truenas-key, konto techniczne', message)
        self.assertNotIn('secret contents', message)
        self.assertNotIn('--wznow', message)
        self.assertTrue(all(call.args[0].endswith('.query') for call in client.call.call_args_list))

    def test_previous_complete_preparation_prints_quoted_resume_command(self):
        with tempfile.TemporaryDirectory(prefix='pcc space ') as directory:
            private = Path(directory)
            for name in install_pl.PREPARATION_FILES:
                (private / name).touch()
            client = Mock()
            client.call.return_value = [{'id': 1}]
            with self.assertRaises(ValueError) as raised:
                install_pl.check_previous_preparation(client, private)
            self.assertIn(f"--wznow '{private / 'settings.json'}'", str(raised.exception))

    def run_wizard(self, *mode):
        client = Mock()
        client.return_value.__enter__ = Mock(return_value=Mock())
        client.return_value.__exit__ = Mock(return_value=False)
        arguments = [
            'install_pl', *mode, '--ip', '192.168.1.120',
            '--archiwa', '/mnt/ArchivePool/Family', '--folder', 'Moje kopie', '--port', '8787',
        ]
        with patch.object(sys, 'argv', arguments), \
             patch.dict(sys.modules, {'truenas_api_client': SimpleNamespace(Client=client)}), \
             patch.object(install_pl.os, 'geteuid', return_value=0), \
             patch.object(install_pl, 'check_host'):
            return install_pl.main()

    def test_check_never_sets_up_credentials_or_deploys(self):
        with patch.object(install_pl, 'private_directory', side_effect=lambda path: path), \
             patch.object(install_pl, 'preflight') as preflight, \
             patch.object(install_pl, 'settings') as settings, \
             patch.object(install_pl, 'deploy') as deploy:
            self.assertIsNone(self.run_wizard('sprawdz'))
        preflight.assert_called_once()
        self.assertEqual(str(preflight.call_args.args[2]), '/mnt/ArchivePool/PCC-Private')
        settings.assert_not_called()
        deploy.assert_not_called()

    def test_fresh_install_uses_the_wizards_confirmation(self):
        mask = os.umask(0o022)
        self.addCleanup(os.umask, mask)
        observed_masks = []

        def call_deployer(*args):
            inherited = os.umask(0o022)
            os.umask(inherited)
            observed_masks.append(inherited)
            return 0

        with patch.object(install_pl, 'private_directory', side_effect=lambda path: path), \
             patch.object(install_pl, 'settings', return_value='/private/settings.json'), \
             patch.object(install_pl.subprocess, 'call', side_effect=call_deployer) as call:
            self.assertEqual(self.run_wizard(), 0)
        call.assert_called_once_with(['sh', 'deploy/install.sh', '/private/settings.json', '--confirmed'])
        self.assertEqual(observed_masks, [0o022])

    def test_secret_file_is_private_at_creation_under_a_permissive_umask(self):
        mask = os.umask(0)
        self.addCleanup(os.umask, mask)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'truenas-key'
            with patch.object(install_pl.os, 'fchown',
                              side_effect=lambda fd, *_: self.assertEqual(stat.S_IMODE(os.fstat(fd).st_mode), 0o600)):
                install_pl.save(path, 'secret')
            self.assertEqual(path.read_text(), 'secret')

    def test_retry_still_requests_confirmation(self):
        with patch.object(install_pl.subprocess, 'call', return_value=0) as call:
            self.assertEqual(self.run_wizard('--wznow', '/private/settings.json'), 0)
        call.assert_called_once_with(['sh', 'deploy/install.sh', '/private/settings.json'])

    def test_desktop_uses_entered_panel_password_and_stages_only_the_verifier(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / 'old'
            staging = Path(directory) / 'staging'
            client = Mock()
            client.call.side_effect = [12, {"gid": 12}, None, None, {"key": "technical-api-key"}]
            args = SimpleNamespace(krok="instaluj", desktop=True)
            with patch.object(install_pl, 'preflight', return_value=({"panel": {}, "connection": {}}, "PEM")), \
                 patch.object(install_pl, 'previous_preparation', return_value=([], {})), \
                 patch.object(install_pl, 'require_fresh_app'), \
                 patch.object(install_pl, 'save') as save, \
                 patch.object(install_pl, 'ask_password_verifier', return_value='stored-verifier') as ask, \
                 patch('builtins.input', return_value='tak'):
                self.assertEqual(install_pl.settings(client, args, private, staging=staging), staging / 'settings.json')
            ask.assert_called_once_with()
            self.assertFalse(private.exists())
            self.assertTrue(all(entry.args[0].parent == staging for entry in save.call_args_list))
            save.assert_any_call(staging / 'panel-verifier', 'stored-verifier\n', owner=568)

    def test_desktop_menu_offers_resume_only_before_app_creation(self):
        with patch('builtins.input', side_effect=['3', '2']) as prompt:
            self.assertEqual(install_pl.choose_action(True), 'sprawdz')
        self.assertEqual(prompt.call_count, 2)
        with patch('builtins.input', return_value='3'):
            self.assertEqual(install_pl.choose_action(False), 'wznowienie')

    def test_resume_checks_saved_parameters_against_current_preflight(self):
        import json
        values = {
            'panel': {'host_ip': '192.168.1.120', 'host_port': 8787},
            'backup': {'archive_parent': '/mnt/ArchivePool/Family', 'folder_name': 'Kopie',
                       'archive_prefix': 'PlexConfig'},
            'connection': {'api_url': 'wss://192.168.1.120/api/current'},
        }
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            config = private / 'settings.json'
            config.write_text(json.dumps(values))
            files = [private / name for name in install_pl.PREPARATION_FILES]
            records = dict.fromkeys(method for method, *_ in install_pl.PREPARATION_RECORDS)
            client = Mock()
            with patch.object(install_pl, 'require_fresh_app'), \
                 patch.object(install_pl, 'private_directory', return_value=private), \
                 patch.object(install_pl, '_verify_private_file'), \
                 patch.object(install_pl, 'previous_preparation', return_value=(files, records)), \
                 patch.object(install_pl, 'verified_preparation'), \
                 patch.object(install_pl, 'check_host'), \
                 patch.object(install_pl, 'preflight', return_value=(values, 'PEM')) as preflight:
                self.assertEqual(install_pl.review_resume(client, private), config)
                self.assertEqual(preflight.call_args.args[1].folder, 'Kopie')
                preflight.return_value = ({**values, 'connection': {}}, 'PEM')
                with self.assertRaisesRegex(ValueError, 'różnią się'):
                    install_pl.review_resume(client, private)

    def test_desktop_reuses_only_a_confirmed_ipv4_server_address(self):
        address = ipaddress.IPv4Address('192.168.1.120')
        connection = ['192.168.1.20', '52111', str(address), '22']
        self.assertEqual(install_pl.ssh_server_address(connection, [address]), address)
        self.assertIsNone(install_pl.ssh_server_address(connection, []))
        self.assertIsNone(install_pl.ssh_server_address(connection[:3], [address]))
        connection[2] = '::1'
        self.assertIsNone(install_pl.ssh_server_address(connection, [address]))

    def test_desktop_check_accepts_verified_leftovers_without_removing_them(self):
        client = Mock()
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            path = private / 'settings.json'
            path.touch(mode=0o600)
            client.call.side_effect = [[], [], [], [], []]
            with patch.object(Path, 'lstat', return_value=SimpleNamespace(
                    st_mode=stat.S_IFREG | 0o600, st_uid=0)), patch('builtins.print') as output:
                install_pl.check_previous_preparation(client, private, allow_reset=True)
            self.assertTrue(path.exists())
        self.assertIn('Można przejść do świeżej instalacji', str(output.call_args_list))
        self.assertNotIn('--wznow', str(output.call_args_list))
        self.assertTrue(all(entry.args[0].endswith('.query') for entry in client.call.call_args_list))

    def test_desktop_check_still_rejects_an_unrelated_api_key(self):
        client = Mock()
        client.call.side_effect = [[], [], [], [{'id': 1, 'username': 'admin'}]]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'innego konta'):
                install_pl.check_previous_preparation(client, Path(directory), allow_reset=True)
        self.assertTrue(all(entry.args[0].endswith('.query') for entry in client.call.call_args_list))
