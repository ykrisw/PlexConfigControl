"""Keep the local panel/journal available while API TLS requires maintenance.

No storage plan is guessed or cached as authority: each execution owner is built
through the original verified storage discovery before any operation is admitted.
"""
from pathlib import Path
import threading
from .execution import ExecutionGateway
from .execution_journal import ExecutionJournal
from .history import History
from .locking import operation_lock
from .progress import Progress
from .startup import reconcile_startup
from .state import StateStore


class DeferredWorker:
    def __init__(self,state,archives,api,factory):
        self.state,self.destination=Path(state),Path(archives)
        self.api,self.factory=api,factory
        self.journal=ExecutionJournal(self.state)
        self.owner=None
        self.lock=threading.RLock()
        self.closing=False

    def gateway(self):
        return ExecutionGateway(self.state,self.destination,self.api,self,
            receipt_lookup=self.journal.lookup,status_reader=self.journal.current,status_lookup=self.journal.status)

    def reconcile_startup(self):
        reconcile_startup(StateStore(self.state),Progress(self.state),History(self.state),self.state)
        self.journal.reconcile_startup()

    def _owner(self):
        with self.lock:
            if self.closing:raise RuntimeError('Worker is stopping')
            if self.owner is None:self.owner=self.factory()
            return self.owner

    def submit(self,request):
        return self._owner().submit(request)

    def delete_archives(self,archives):
        return self._owner().delete_archives(archives)

    def close(self):
        with self.lock:
            self.closing=True
            if self.owner is not None:self.owner.close()
