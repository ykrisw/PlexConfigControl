"""Private durable admission/ownership ledger; never executes or retries work.

Deployment must still hold the operation-wide lock and recheck coordinator gates.
Only request fingerprints are stored, not archive names, commands, passwords or
request bodies. Clearing web History never touches this database. Reconciliation
is explicitly invoked once by the execution owner's startup, not each HTTP worker.
"""
import hashlib
import json
import re
import secrets
import sqlite3
import time
from dataclasses import asdict, dataclass
from contextlib import contextmanager
from pathlib import Path

from .archive_store import Archive
from .execution import (AcceptedOperation, BackupRequest, RestoreRequest,
                        InvalidExecutionRequest, _identity, _request_id)
from .locking import OperationBusy, operation_lock
from .operations import OperationDenied, Phase
from .publication_intent import pending
from .state import StateStore


@dataclass(frozen=True)
class Reservation:
    receipt: AcceptedOperation
    created: bool
    state: str


@dataclass(frozen=True)
class OperationClaim:
    receipt: AcceptedOperation
    token: str  # Private execution ownership; never include in HTTP receipts.


def request_fingerprint(request):
    if type(request) not in (BackupRequest, RestoreRequest):
        raise InvalidExecutionRequest('Fixed Backup or Restore request required')
    payload = asdict(request)
    _request_id(payload)
    if isinstance(request, BackupRequest):
        kind = 'BACKUP'
        if request.mode not in ('NEW', 'ANOTHER', 'OVERWRITE'):
            raise InvalidExecutionRequest('Invalid Backup mode')
        if request.mode == 'NEW':
            if request.archive is not None:
                raise InvalidExecutionRequest('New-copy request cannot select an archive')
        elif type(request.archive) is not Archive:
            raise InvalidExecutionRequest('Exact archive identity required')
        else:
            _identity(payload['archive'])
    else:
        from .archive_store import NAME
        kind = 'RESTORE'
        if (not isinstance(request.archive, str) or not NAME.fullmatch(request.archive)
                or not isinstance(request.sha256, str)
                or not re.fullmatch(r'[0-9a-f]{64}', request.sha256)
                or request.confirmation != 'RESTORE'):
            raise InvalidExecutionRequest('Validated Restore request required')
    encoded = json.dumps({'kind':kind, 'request':payload}, sort_keys=True,
                         separators=(',', ':'), ensure_ascii=True).encode()
    return kind, hashlib.sha256(encoded).hexdigest()


class ExecutionJournal:
    def __init__(self, state_directory):
        self.directory = Path(state_directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.directory/'execution.sqlite3'
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS requests (
                request_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                fingerprint TEXT NOT NULL, state TEXT NOT NULL,
                owner_hash TEXT, created_ns INTEGER NOT NULL, updated_ns INTEGER NOT NULL,
                CHECK(kind IN ('BACKUP','RESTORE')),
                CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','RECOVERY_REQUIRED')))''')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_request ON requests((1)) "
                       "WHERE state IN ('QUEUED','RUNNING','RECOVERY_REQUIRED')")
        self.path.chmod(0o600)

    @contextmanager
    def _connect(self):
        if self.path.is_symlink():
            raise ValueError('Execution journal cannot be a symlink')
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _same(row, kind, fingerprint):
        if row['kind'] != kind or not secrets.compare_digest(row['fingerprint'], fingerprint):
            raise OperationDenied('Request identity was already used for different operation data')

    def lookup(self, request):
        kind, fingerprint = request_fingerprint(request)
        with self._connect() as db:
            row = db.execute('SELECT * FROM requests WHERE request_id=?', (request.request_id,)).fetchone()
        if row is None:
            return None
        self._same(row, kind, fingerprint)
        return AcceptedOperation(request.request_id, kind)

    def reserve(self, request):
        kind, fingerprint = request_fingerprint(request)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM requests WHERE request_id=?', (request.request_id,)).fetchone()
            if row is not None:
                self._same(row, kind, fingerprint)
                return Reservation(AcceptedOperation(request.request_id, kind), False, row['state'])
            if db.execute("SELECT 1 FROM requests WHERE state IN ('QUEUED','RUNNING','RECOVERY_REQUIRED')").fetchone():
                raise OperationBusy('An admitted operation or recovery is outstanding')
            now = time.time_ns()
            db.execute('INSERT INTO requests VALUES(?,?,?,?,NULL,?,?)',
                       (request.request_id, kind, fingerprint, 'QUEUED', now, now))
        return Reservation(AcceptedOperation(request.request_id, kind), True, 'QUEUED')

    def claim(self, request):
        kind, fingerprint = request_fingerprint(request)
        token = secrets.token_hex(32)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM requests WHERE request_id=?', (request.request_id,)).fetchone()
            if row is None:
                raise OperationDenied('Operation must be admitted before execution')
            self._same(row, kind, fingerprint)
            if row['state'] != 'QUEUED':
                raise OperationDenied('Operation is already claimed, finished or awaiting recovery')
            db.execute("UPDATE requests SET state='RUNNING',owner_hash=?,updated_ns=? WHERE request_id=?",
                       (hashlib.sha256(token.encode()).hexdigest(), time.time_ns(), request.request_id))
        return OperationClaim(AcceptedOperation(request.request_id, kind), token)

    def finish(self, claim, outcome):
        # Caller has independently verified coordinator result/cleanup. This
        # ledger is not proof of successful archive creation or restored data.
        if (type(claim) is not OperationClaim or type(claim.receipt) is not AcceptedOperation
                or not isinstance(claim.token, str) or not re.fullmatch(r'[0-9a-f]{64}', claim.token)
                or outcome not in ('SUCCEEDED','FAILED','RECOVERY_REQUIRED')):
            raise OperationDenied('Valid owned execution result required')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE requests SET state=?,owner_hash=NULL,updated_ns=? "
                "WHERE request_id=? AND kind=? AND state='RUNNING' AND owner_hash=?",
                (outcome, time.time_ns(), claim.receipt.request_id, claim.receipt.kind,
                 hashlib.sha256(claim.token.encode()).hexdigest())).rowcount
            if changed != 1:
                raise OperationDenied('Execution claim is no longer current')

    def reconcile_startup(self):
        # A live coordinator's lock prevents a new execution owner from treating
        # its work as interrupted. No requests are requeued or replayed.
        with operation_lock(self.directory), self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute("SELECT request_id FROM requests WHERE state IN ('QUEUED','RUNNING')").fetchall()
            db.execute("UPDATE requests SET state='RECOVERY_REQUIRED',owner_hash=NULL,updated_ns=? "
                       "WHERE state IN ('QUEUED','RUNNING')", (time.time_ns(),))
        return [row['request_id'] for row in rows]

    def resolve_interrupted(self, request_id, *, confirmed=False):
        if confirmed is not True or not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{32}', request_id):
            raise OperationDenied('Confirm the exact interrupted request')
        with operation_lock(self.directory):
            with StateStore(self.directory).transaction() as operation:
                if (operation.phase not in (Phase.IDLE,Phase.SUCCESS,Phase.FAILED)
                        or operation.snapshot_id or pending(self.directory)):
                    raise OperationDenied('Coordinator recovery must be verified first')
            if any(path.name.startswith(('backup-', 'restore-')) for path in self.directory.iterdir()):
                raise OperationDenied('Private operation workspace requires inspection')
            with self._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                changed = db.execute("UPDATE requests SET state='FAILED',owner_hash=NULL,updated_ns=? "
                    "WHERE request_id=? AND state='RECOVERY_REQUIRED'", (time.time_ns(), request_id)).rowcount
                if changed != 1:
                    raise OperationDenied('Exact interrupted request is not awaiting recovery')
