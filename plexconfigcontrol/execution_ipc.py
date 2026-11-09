"""A local, fixed-purpose bridge to the separate execution owner."""
import json
import socket
import socketserver
import struct
from pathlib import Path
from dataclasses import asdict

from .execution import (
    AcceptedOperation, BackupRequest, ExecutionGateway, InvalidExecutionRequest,
    RestoreRequest, SubmissionUnconfirmed, parse_archive_deletion, parse_backup_request, parse_restore_request,
)
from .archive_store import ArchiveChanged
from .locking import OperationBusy
from .operations import OperationDenied


# Fit the 16 KiB HTTP deletion body plus the IPC binding and envelope.
MAX_FRAME = 20 * 1024
TIMEOUT = 30


def _peer_uid(connection):
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    return struct.unpack('3i', credentials)[1]


def _read(connection):
    with connection.makefile('rb') as stream:
        frame = stream.readline(MAX_FRAME + 1)
    if len(frame) > MAX_FRAME or not frame.endswith(b'\n'):
        raise ValueError('Invalid execution message')
    return json.loads(frame)


def _send(connection, data):
    frame = json.dumps(data, separators=(',', ':'), ensure_ascii=True).encode() + b'\n'
    if len(frame) > MAX_FRAME:
        raise ValueError('Invalid execution message size')
    connection.sendall(frame)


def _binding(state, archives):
    # The same directory retains its device/inode across local bind mounts.
    return [[info.st_dev, info.st_ino] for info in (state.stat(), archives.stat())]


def _payload(request):
    data = asdict(request)
    if isinstance(request, BackupRequest):
        if data['archive'] is None:
            del data['archive']
        if data['prefix'] is None:
            del data['prefix']
        data['confirmed'] = True
        return 'backup', data
    if isinstance(request, RestoreRequest):
        return 'restore', data
    raise InvalidExecutionRequest('Fixed operation request required')


class _ExecutionHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(TIMEOUT)
        try:
            result = self.server.dispatch(_read(self.request))
            reply = {'result': result}
        except (OperationBusy, OperationDenied, ArchiveChanged, FileNotFoundError):
            reply = {'error': 'denied'}
        except (InvalidExecutionRequest, ValueError, TypeError):
            reply = {'error': 'invalid'}
        except Exception:
            reply = {'error': 'unconfirmed'}
        try:
            _send(self.request, reply)
        except OSError:
            pass  # The worker's durable receipt is the source of truth.


class ExecutionSocketServer(socketserver.UnixStreamServer):
    def __init__(self, path, worker, panel_uid):
        self.gateway = worker.gateway()
        self.worker = worker
        self.panel_uid = panel_uid
        super().__init__(str(path), _ExecutionHandler)

    def verify_request(self, request, client_address):
        return _peer_uid(request) == self.panel_uid

    def dispatch(self, message):
        if not isinstance(message, dict) or set(message) != {'action', 'data', 'binding'}:
            raise InvalidExecutionRequest('Invalid execution message')
        if message['binding'] != _binding(self.gateway.state, self.gateway.destination):
            raise OperationDenied('Panel and worker storage do not match')
        action, data = message['action'], message['data']
        if action == 'plex' and data is None:
            return self.gateway.api.call('app.query', [['name', '=', 'plex']])
        if action == 'status':
            if not isinstance(data, dict) or set(data) != {'request_id'}:
                raise InvalidExecutionRequest('Invalid status request')
            return self.gateway.status(data['request_id'])
        if action == 'backup':
            return self.gateway.backup(data)
        if action == 'restore':
            return self.gateway.restore(data)
        if action == 'delete_archives':
            return self.worker.delete_archives(parse_archive_deletion(data))
        if action == 'lookup_backup':
            return self.gateway._lookup(parse_backup_request(data), 'BACKUP')
        if action == 'lookup_restore':
            return self.gateway._lookup(parse_restore_request(data), 'RESTORE')
        raise InvalidExecutionRequest('Unknown execution action')


class ExecutionSocketClient:
    def __init__(self, path, worker_uid, state, archives):
        self.path = str(path)
        self.worker_uid = worker_uid
        self.state, self.archives = Path(state), Path(archives)

    def _call(self, action, data):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(TIMEOUT)
                connection.connect(self.path)
                if _peer_uid(connection) != self.worker_uid:
                    raise ValueError('Unexpected execution owner')
                _send(connection, {'action': action, 'data': data,
                                   'binding': _binding(self.state, self.archives)})
                reply = _read(connection)
        except (OSError, ValueError) as error:
            raise SubmissionUnconfirmed('Execution owner reply could not be verified') from None
        if isinstance(reply, dict):
            if set(reply) == {'result'}:
                return reply['result']
            if reply == {'error': 'denied'}:
                raise OperationDenied('Execution owner denied the request')
            if reply == {'error': 'invalid'}:
                raise InvalidExecutionRequest('Execution owner rejected the request')
        raise SubmissionUnconfirmed('Execution owner reply could not be verified')

    def _receipt(self, request, lookup=False):
        kind, data = _payload(request)
        result = self._call('lookup_' + kind if lookup else kind, data)
        if lookup and result is None:
            return None
        expected = {'accepted': True, 'request_id': request.request_id, 'kind': kind.upper(),
                    'status_url': '/api/operation'}
        if result != expected or result['accepted'] is not True:
            raise SubmissionUnconfirmed('Execution receipt could not be verified')
        return AcceptedOperation(request.request_id, kind.upper())

    def submit(self, request):
        return self._receipt(request)

    def lookup(self, request):
        return self._receipt(request, lookup=True)

    def status(self, request_id=None):
        return self._call('status', {'request_id': request_id})

    def delete_archives(self, archives):
        result = self._call('delete_archives', {'archives': [asdict(item) for item in archives],
                                                'confirmed': True})
        if result != [item.name for item in archives]:
            raise SubmissionUnconfirmed('Archive deletion could not be verified')
        return result

    def call(self, method, *params):
        if method != 'app.query':
            raise PermissionError('Only Plex status is available through this adapter')
        return self._call('plex', None)

    def gateway(self):
        return ExecutionGateway(self.state, self.archives, self, self,
                                receipt_lookup=self.lookup,
                                status_reader=self.status, status_lookup=self.status)
