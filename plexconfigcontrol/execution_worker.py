"""Optional single-operation runner; no credentials, commands or privileges added.

Trusted deployment supplies fixed Backup/Restore factories, scoped API and paths.
The restricted runtime does not construct this class. A non-daemon thread holds
the operation lock from admission through coordinator reporting/journal completion.
"""
import threading
from contextlib import contextmanager
from pathlib import Path

from .archive_store import ArchiveStore, archive_matches
from .backup import Backup
from .execution import BackupRequest, RestoreRequest, ExecutionGateway
from .execution_journal import ExecutionJournal
from .locking import operation_lock, OperationBusy
from .operations import Phase, OperationDenied
from .plex import PlexStatus
from .progress import Progress
from .publication_intent import pending
from .restore import Restore
from .snapshots import Snapshots
from .state import StateStore


class _BorrowedGuard:
    def __init__(self, state):
        self.state, self.owner, self.used = state, None, False

    @contextmanager
    def __call__(self, state):
        if (self.owner != threading.get_ident() or self.used
                or Path(state).resolve() != self.state):
            raise OperationDenied('Reserved execution lock cannot be reused or redirected')
        self.used = True
        yield


class _Handoff:
    def __init__(self):
        self.owner = 'parent'
        self.ready = threading.Event()


class ExecutionWorker:
    def __init__(self, state_directory, archive_directory, dataset, api,
                 backup_factory, restore_factory, *, thread_factory=threading.Thread):
        if api is None or not all(callable(factory) for factory in (backup_factory,restore_factory)):
            raise ValueError('Explicit scoped API and fixed coordinator factories required')
        Snapshots(None,None,dataset)
        self.state = Path(state_directory).resolve()
        self.destination = Path(archive_directory).resolve()
        self.dataset, self.api = dataset, api
        self.backup_factory, self.restore_factory = backup_factory, restore_factory
        self.thread_factory = thread_factory
        self.store = StateStore(self.state)
        self.journal = ExecutionJournal(self.state)
        self._lifecycle = threading.RLock()
        self._threads = set()
        self._closing = False

    def gateway(self):
        return ExecutionGateway(self.state,self.destination,self.api,self,
            receipt_lookup=self.journal.lookup,status_reader=self.journal.current)

    def _admit(self, request):
        # Caller owns operation_lock. No network I/O inside SQLite transactions.
        with self.store.transaction() as operation:
            phase, kind, snapshot = operation.phase, operation.kind, operation.snapshot_id
            details = operation.validation_details or {}
            digest, outcome = operation.archive_identity, operation.outcome
        if snapshot or pending(self.state):
            raise OperationBusy('Recovery must finish before execution')
        if isinstance(request,BackupRequest):
            if phase not in (Phase.IDLE,Phase.SUCCESS,Phase.FAILED):
                raise OperationBusy('Another operation is active')
            rows = ArchiveStore(self.destination,self.state).list()
            if request.mode == 'NEW':
                if len(rows) == 1:
                    raise OperationDenied('Single-copy decision required')
            elif len(rows) != 1 or rows[0] != request.archive:
                raise OperationDenied('Confirmed archive identity changed')
            expected = 'RUNNING'
        else:
            if (kind != 'RESTORE' or phase not in (Phase.WAITING_FOR_PLEX_STOP,Phase.READY)
                    or outcome is not None or details.get('status') != 'VALID'
                    or details.get('archive') != request.archive or digest != request.sha256
                    or details.get('sha256') != request.sha256
                    or not archive_matches(self.destination,request.archive,details.get('file_identity'))):
                raise OperationDenied('Restore checkpoint or archive changed')
            expected = 'STOPPED'
        if PlexStatus(self.api).read()['state'] != expected:
            raise OperationDenied('Required Plex state is not confirmed')

    def submit(self, request):
        previous = self.journal.lookup(request)  # Also validates the fixed type/payload.
        if previous is not None:
            return previous
        with self._lifecycle:
            if self._closing:
                raise OperationBusy('Execution owner is shutting down')
            guard = operation_lock(self.state)
            guard.__enter__()
            handoff = _Handoff()
            claim = None
            thread = None
            try:
                previous = self.journal.lookup(request)
                if previous is not None:
                    return previous
                self._admit(request)
                reservation = self.journal.reserve(request)
                if not reservation.created:
                    return reservation.receipt
                claim = self.journal.claim(request)
                borrowed = _BorrowedGuard(self.state)
                thread = self.thread_factory(target=self._work,
                    args=(request,claim,guard,borrowed,handoff),
                    name='pcc-operation',daemon=False)
                self._threads.add(thread)
                thread.start()
                # Single ownership assignment: even an interrupt immediately
                # afterwards cannot release a lock which the worker will use.
                handoff.owner = 'worker'
                return reservation.receipt
            except BaseException:
                if handoff.owner == 'parent':
                    if thread is not None:
                        self._threads.discard(thread)
                    if claim is not None:
                        try: self.journal.finish(claim,'FAILED')
                        except Exception: pass  # Uncertain admission stays blocked.
                raise
            finally:
                handoff.ready.set()
                if handoff.owner == 'parent':
                    guard.__exit__(None,None,None)

    def _coordinator(self, request, borrowed):
        coordinator = (self.backup_factory() if isinstance(request,BackupRequest)
                       else self.restore_factory())
        expected_type = Backup if isinstance(request,BackupRequest) else Restore
        if (type(coordinator) is not expected_type or coordinator.state.resolve() != self.state
                or coordinator.destination.resolve() != self.destination
                or coordinator.dataset != self.dataset or coordinator.api is not self.api
                or coordinator.store.directory.resolve() != self.state
                or coordinator.history.path.parent.resolve() != self.state
                or coordinator.progress.path.parent.resolve() != self.state):
            raise OperationDenied('Coordinator does not match the fixed execution scope')
        coordinator._operation_guard = borrowed
        coordinator._execution_request_id = request.request_id
        return coordinator

    def _success(self, request, result, borrowed):
        expected_kind = 'BACKUP' if isinstance(request,BackupRequest) else 'RESTORE'
        archive = result if expected_kind == 'BACKUP' else request.archive
        with self.store.transaction() as operation:
            verified = (borrowed.used and operation.execution_request_id == request.request_id
                and operation.kind == expected_kind
                and operation.phase == Phase.SUCCESS and operation.snapshot_id is None
                and operation.outcome == {'code':expected_kind+'_COMPLETED','archive':archive})
        if (not verified or pending(self.state) or self._workspaces()
                or Progress(self.state).read()['stage'] != 'COMPLETED'):
            raise RuntimeError('Coordinator success was not independently confirmed')

    def _workspaces(self):
        return any(path.name.startswith(('backup-','restore-')) for path in self.state.iterdir())

    def _failed_state(self):
        with self.store.transaction() as operation:
            recovery = (bool(operation.snapshot_id) or operation.phase in
                        (Phase.VALIDATING,Phase.RUNNING,Phase.RECOVERY_REQUIRED)
                        or (operation.outcome or {}).get('code') in
                           ('BACKUP_IN_PROGRESS','RESTORE_IN_PROGRESS'))
        return 'RECOVERY_REQUIRED' if recovery or pending(self.state) or self._workspaces() else 'FAILED'

    def _work(self, request, claim, guard, borrowed, handoff):
        handoff.ready.wait()
        if handoff.owner != 'worker':
            return
        borrowed.owner = threading.get_ident()
        outcome = 'RECOVERY_REQUIRED'
        try:
            coordinator = self._coordinator(request,borrowed)
            if isinstance(request,BackupRequest):
                if request.mode == 'OVERWRITE': result = coordinator.run_overwrite(request.archive)
                else: result = coordinator.run_new(create_another=request.archive)
            else:
                # Payload-bound digest/name were checked while this same lock
                # was reserved; validation/cancel routes cannot replace them.
                result = coordinator.run(request.archive,request.confirmation)
            self._success(request,result,borrowed)
            outcome = 'SUCCEEDED'
        except Exception:
            try: outcome = self._failed_state()
            except Exception: pass
        except BaseException:
            pass  # Unexpected interruption is never success or automatic retry.
        finally:
            try:
                self.journal.finish(claim,outcome)
            except Exception:
                pass  # Keep uncertain durable claim for explicit reconciliation.
            finally:
                guard.__exit__(None,None,None)
                with self._lifecycle:
                    self._threads.discard(threading.current_thread())

    def reconcile_startup(self):
        # Explicit execution-owner startup only; never auto-replay a queued job.
        from .startup import reconcile_startup
        from .history import History
        with self._lifecycle:
            if self._threads:
                raise OperationBusy('Execution owner still has live work')
            coordinator = reconcile_startup(self.store,Progress(self.state),History(self.state),self.state)
            requests = self.journal.reconcile_startup()
        return {'coordinator':coordinator,'requests':requests}

    def close(self):
        with self._lifecycle:
            self._closing = True
            threads = list(self._threads)
        for thread in threads:
            thread.join()
