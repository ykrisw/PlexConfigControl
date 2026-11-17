import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from plexconfigcontrol.archive_store import ArchiveStore
from plexconfigcontrol.execution import AcceptedOperation, BackupRequest, SubmissionUnconfirmed
from plexconfigcontrol.execution_ipc import ExecutionSocketClient, ExecutionSocketServer, _binding
from plexconfigcontrol.operations import OperationDenied


class ExecutionIPCTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.state = self.root/'state'
        self.archives = self.root/'archives'
        self.state.mkdir()
        self.archives.mkdir()
        self.request = BackupRequest('a'*32, 'NEW', prefix='Living-Room')
        self.receipt = {'accepted': True, 'request_id': self.request.request_id,
                        'kind': 'BACKUP', 'status_url': '/api/operation'}
        self.gateway = Mock(state=self.state, destination=self.archives)
        self.gateway.backup.return_value = self.receipt
        self.gateway._lookup.return_value = self.receipt

    def test_fixed_actions_and_same_storage_are_required(self):
        worker = Mock()
        server = SimpleNamespace(gateway=self.gateway, worker=worker)
        dispatch = lambda action, data, binding: ExecutionSocketServer.dispatch(
            server, {'action': action, 'data': data, 'binding': binding})
        binding = _binding(self.state, self.archives)
        data = {'request_id': self.request.request_id, 'mode': 'NEW', 'confirmed': True,
                'prefix': 'Living-Room'}
        with self.assertRaises(OperationDenied):
            dispatch('backup', data, list(reversed(binding)))
        with self.assertRaises(ValueError):
            dispatch('shell', data, binding)
        with self.assertRaises(ValueError):
            dispatch('lookup_backup', {**data, 'prefix': '../wrong'}, binding)
        self.gateway.backup.assert_not_called()
        self.gateway._lookup.assert_not_called()
        self.assertEqual(dispatch('backup', data, binding), self.receipt)
        self.assertEqual(dispatch('lookup_backup', data, binding), self.receipt)
        self.gateway._lookup.assert_called_once_with(self.request, 'BACKUP')
        selection = {'archives': [{'name': '../Backup.log', 'size': 1,
                                    'device': 2, 'inode': 3, 'modified_ns': 4}],
                     'confirmed': True}
        with self.assertRaises(ValueError):
            dispatch('delete_archives', selection, binding)
        worker.delete_archives.assert_not_called()
        selection['archives'][0]['name'] = 'PlexConfig_2026.11.09_17.58.28.tar.gz'
        dispatch('delete_archives', selection, binding)
        worker.delete_archives.assert_called_once()

    def test_unix_socket_checks_worker_uid_and_transports_verified_receipts(self):
        try:
            with socket.socket(socket.AF_UNIX):
                pass
        except PermissionError:
            self.skipTest('Unix sockets are unavailable in this runner')
        path = self.root/'worker.sock'
        worker = Mock()
        worker.gateway.return_value = self.gateway
        archives = ArchiveStore(self.archives, self.state)
        archive = self.archives/'PlexConfig_2026.11.09_17.58.28.tar.gz'
        archive.write_bytes(b'backup')
        worker.delete_archives.side_effect = lambda selected: archives.delete(selected, confirmed=True)
        with ExecutionSocketServer(path, worker, os.getuid()) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                client = ExecutionSocketClient(path, os.getuid(), self.state, self.archives)
                self.assertEqual(client.submit(self.request), AcceptedOperation(self.request.request_id, 'BACKUP'))
                self.assertEqual(client.lookup(self.request), AcceptedOperation(self.request.request_id, 'BACKUP'))
                impostor = ExecutionSocketClient(path, os.getuid()+1, self.state, self.archives)
                with self.assertRaises(SubmissionUnconfirmed):
                    impostor.submit(self.request)
                self.gateway.backup.assert_called_once()
                self.assertEqual(client.delete_archives(archives.list()), [archive.name])
                self.assertFalse(archive.exists())
            finally:
                server.shutdown()
                thread.join()
