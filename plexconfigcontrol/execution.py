"""Fixed operation requests for a separately configured execution backend.

This module never executes commands or grants host privileges. A deployment
backend must durably deduplicate request_id, reserve the operation before returning
AcceptedOperation, recheck all identities/gates inside the coordinator lock, and
publish progress to the same private state directory. There is no default backend
and the restricted runtime never supplies one. Acceptance is not operation success.
"""
import re
from dataclasses import dataclass
from pathlib import Path
from .archive_store import Archive, NAME
from .backup_plan import plan_backup
from .operations import OperationDenied
from .locking import OperationBusy
from .plex import PlexStatus
from .restore_readiness import restore_readiness
from .state import StateStore


class InvalidExecutionRequest(ValueError):
    pass


class SubmissionUnconfirmed(RuntimeError):
    pass


def _identity(value):
    if not isinstance(value, dict) or set(value) != set(Archive.__dataclass_fields__):
        raise InvalidExecutionRequest('Confirm the exact displayed archive')
    if not isinstance(value['name'], str) or not NAME.fullmatch(value['name']):
        raise InvalidExecutionRequest('Choose a recognized archive')
    numbers = {}
    for key in ('size', 'device', 'inode', 'modified_ns'):
        item = value[key]
        if (isinstance(item, str) and re.fullmatch(r'0|[1-9][0-9]{0,19}', item)
                and int(item) < 2**64):
            numbers[key] = int(item)
        elif type(item) is int and 0 <= item < 2**64:
            numbers[key] = item
        else:
            raise InvalidExecutionRequest('Invalid archive identity')
    return Archive(value['name'], **numbers)


def _request_id(data):
    value = data.get('request_id')
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}', value):
        raise InvalidExecutionRequest('A new operation request identity is required')
    return value


@dataclass(frozen=True)
class BackupRequest:
    request_id: str
    mode: str
    archive: Archive | None = None


@dataclass(frozen=True)
class RestoreRequest:
    request_id: str
    archive: str
    sha256: str
    confirmation: str


@dataclass(frozen=True)
class AcceptedOperation:
    request_id: str
    kind: str


class ExecutionGateway:
    def __init__(self, state_directory, archive_directory, api, backend, *, receipt_lookup=None):
        self.state = Path(state_directory).resolve()
        self.destination = Path(archive_directory).resolve()
        if api is None or not callable(getattr(backend, 'submit', None)):
            raise ValueError('Explicit execution backend and Plex status connection required')
        if receipt_lookup is not None and not callable(receipt_lookup):
            raise ValueError('Receipt lookup must be explicitly configured')
        self.receipt_lookup = receipt_lookup
        self.store = StateStore(self.state)
        self.api, self.backend = api, backend

    def _submit(self, request, kind):
        try:
            receipt = self.backend.submit(request)
        except (OperationBusy, OperationDenied):
            raise
        except Exception:
            raise SubmissionUnconfirmed('Operation submission was not confirmed') from None
        return self._receipt(request, kind, receipt)

    @staticmethod
    def _receipt(request, kind, receipt):
        if (not isinstance(receipt, AcceptedOperation) or receipt.kind != kind
                or receipt.request_id != request.request_id):
            raise SubmissionUnconfirmed('Operation submission was not confirmed')
        return {'accepted':True, 'request_id':receipt.request_id, 'kind':kind,
                'status_url':'/api/operation'}

    def _lookup(self, request, kind):
        if self.receipt_lookup is None:
            return None
        try:
            receipt = self.receipt_lookup(request)
        except (OperationBusy, OperationDenied):
            raise
        except Exception:
            raise SubmissionUnconfirmed('Previous submission could not be verified') from None
        return None if receipt is None else self._receipt(request, kind, receipt)

    def backup(self, data):
        if not isinstance(data, dict) or set(data) not in (
                {'request_id','mode','confirmed'}, {'request_id','mode','confirmed','archive'}):
            raise InvalidExecutionRequest('Invalid Backup request fields')
        request_id = _request_id(data)
        mode = data.get('mode')
        if mode not in ('NEW','ANOTHER','OVERWRITE') or data.get('confirmed') is not True:
            raise InvalidExecutionRequest('Confirm the Backup action')
        selected = _identity(data.get('archive')) if mode != 'NEW' else None
        if mode == 'NEW' and 'archive' in data:
            raise InvalidExecutionRequest('A new-copy request cannot select an archive')
        request = BackupRequest(request_id, mode, selected)
        previous = self._lookup(request, 'BACKUP')
        if previous is not None:
            return previous
        plan = plan_backup(self.destination, self.state)
        if mode == 'NEW':
            if plan['archive_count'] == 1:
                raise OperationDenied('Choose overwrite or another dated copy')
        elif (plan['archive_count'] != 1 or
              selected != Archive(**plan['existing_archive'])):
            raise OperationDenied('Archive selection changed; refresh and confirm again')
        if PlexStatus(self.api).read()['state'] != 'RUNNING':
            raise OperationDenied('Plex must be confirmed RUNNING before Backup')
        return self._submit(request, 'BACKUP')

    def restore(self, data):
        if (not isinstance(data, dict) or set(data) !=
                {'request_id','archive','sha256','confirmation'}):
            raise InvalidExecutionRequest('Invalid Restore request fields')
        request_id = _request_id(data)
        name, digest = data.get('archive'), data.get('sha256')
        if (not isinstance(name, str) or not NAME.fullmatch(name)
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
                or data.get('confirmation') != 'RESTORE'):
            raise InvalidExecutionRequest('Confirm the selected validated archive with RESTORE')
        request = RestoreRequest(request_id, name, digest, 'RESTORE')
        previous = self._lookup(request, 'RESTORE')
        if previous is not None:
            return previous
        readiness = restore_readiness(self.store, self.state, self.api, self.destination)
        with self.store.transaction() as operation:
            current_digest = operation.archive_identity
        if not readiness['ready'] or readiness['archive'] != name or current_digest != digest:
            raise OperationDenied('Restore readiness changed; refresh and confirm again')
        return self._submit(request, 'RESTORE')
