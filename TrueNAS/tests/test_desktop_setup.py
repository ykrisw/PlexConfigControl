import importlib.util
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(importlib.util.find_spec('paramiko'), 'Desktop dependency is installed in the native build jobs')
class DesktopSetupTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'deploy/desktop/setup_app.py'
        spec = importlib.util.spec_from_file_location('desktop_setup', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_installation_exchange_handles_split_utf8_and_sudo_without_echoing_password(self):
        events = queue.Queue()
        credentials = {'password': 'account-secret'}
        installer = self.module.Installer(events, threading.Event(), set(), credentials)
        channel = Mock()
        prompt = self.module.PREFIX + json.dumps({
            'type': 'prompt', 'message': 'Wybór folderu kopii', 'secret': False,
            'choices': [], 'confirmation': None,
        }, ensure_ascii=False) + '\n'
        text = (self.module.PREFIX + json.dumps({'type': 'stage', 'code': 'BUILD_PANEL'}) + '\n'
                + 'PlexConfigControl gotowy. Otwórz https://192.0.2.10:8787\n').encode()
        prompt_bytes = prompt.encode()
        split = prompt_bytes.index('ó'.encode()) + 1
        channel.recv.side_effect = [b'PCC_SUDO_PASSWORD:', prompt_bytes[:split], prompt_bytes[split:], text, b'']
        channel.recv_exit_status.return_value = 0
        client = Mock()
        stdout = Mock()
        stdout.read.return_value = b'/var/tmp/pcc-gui.aabbccdd\n'
        stdout.channel.recv_exit_status.return_value = 0
        client.exec_command.return_value = (None, stdout, None)
        client.get_transport.return_value.open_session.return_value = channel
        sftp = Mock()
        client.open_sftp.return_value.__enter__ = Mock(return_value=sftp)
        client.open_sftp.return_value.__exit__ = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'setup_app.py'
            (Path(folder) / 'payload').mkdir()
            (Path(folder) / 'payload/PlexConfigControl_Instalator.py').touch()
            with patch.object(self.module, '__file__', str(source)), \
                 patch.object(installer, 'connect', return_value=client), \
                 patch.object(installer, 'ask', return_value='Moje kopie') as ask:
                installer.run('192.0.2.10', 'admin', 'pl')
        self.assertEqual(ask.call_args.args[0]['message'], 'Wybór folderu kopii')
        self.assertIn('stty -echo; sudo -S', channel.exec_command.call_args.args[0])
        self.assertEqual(channel.sendall.call_args_list[0].args[0], b'account-secret\n')
        delivered = []
        while not events.empty():
            delivered.append(events.get_nowait())
        self.assertEqual(delivered[-1], {'type': 'complete', 'url': 'https://192.0.2.10:8787'})
        self.assertNotIn('account-secret', repr(delivered))

    def test_renamed_folder_prompt_has_a_stable_retry_key(self):
        a = {'message': 'Nazwa nowego folderu kopii [Plex Config]: ', 'choices': [], 'secret': False}
        b = {**a, 'message': 'Nazwa nowego folderu kopii [Plex Config 2]: '}
        self.assertEqual(self.module.classify_prompt(a), self.module.classify_prompt(b))

    def test_password_prompt_is_available_without_any_ssh_key(self):
        installer = self.module.Installer(queue.Queue(), threading.Event(), set(), {})
        client = Mock()
        client.connect.side_effect = [self.module.paramiko.SSHException('No authentication methods available'), None]
        with patch.object(self.module.paramiko, 'SSHClient', return_value=client), \
             patch.object(installer, 'ask', return_value='account-secret') as ask:
            self.assertIs(installer.connect('192.0.2.10', 'admin'), client)
        self.assertEqual(ask.call_args.args[0]['type'], 'ssh-password')
        self.assertEqual(client.connect.call_args.kwargs['password'], 'account-secret')

    def test_rejected_entries_show_the_specific_correction_in_both_languages(self):
        for message in ('Hasła się różnią. Wpisz je ponownie.',
                        'The passwords do not match. Enter them again.',
                        'Folder /mnt/Pool/Kopie już istnieje. Wpisz inną nazwę.'):
            self.assertEqual(self.module.prompt_feedback({'context': 'Earlier context\n' + message}), message)
        self.assertEqual(self.module.prompt_feedback({'context': 'Folder kopii: /mnt/Pool/Kopie'}), '')
