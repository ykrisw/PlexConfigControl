"""Restore prevalidation without stopping Plex or changing its configuration."""
import os
import stat
import threading
from pathlib import Path
from .archive_store import NAME, file_identity
from .archives import validate_archive, InvalidArchive
from .locking import operation_lock
from .operations import Phase, OperationDenied
from .publication_intent import pending
from .progress import Progress

class RestoreValidation:
    def __init__(self, archive_directory, state_directory, store, history):
        self.archive_directory=Path(archive_directory)
        self.state_directory=state_directory
        self.store=store
        self.history=history
        self.progress=Progress(state_directory)

    def validate(self, name):
        if not isinstance(name,str) or not NAME.fullmatch(name):
            raise ValueError('Choose a recognized backup archive')
        with operation_lock(self.state_directory):
            if pending(self.state_directory):
                raise OperationDenied('Unresolved archive publication requires recovery')
            with self.store.transaction() as operation:
                operation.begin('RESTORE')
                operation.validation_details={'archive':name,'status':'VALIDATING','reason':None}
            return self._validate_locked(name)

    def start_background(self, name):
        """Reserve synchronously; transfer the held lock to one validation thread.

        Non-daemon worker finishes on normal interpreter shutdown. Unexpected
        process termination leaves VALIDATING for startup reconciliation.
        """
        if not isinstance(name,str) or not NAME.fullmatch(name):
            raise ValueError('Choose a recognized backup archive')
        guard=operation_lock(self.state_directory)
        guard.__enter__()
        reserved=False
        try:
            if pending(self.state_directory):
                raise OperationDenied('Unresolved archive publication requires recovery')
            with self.store.transaction() as operation:
                operation.begin('RESTORE')
                operation.validation_details={'archive':name,'status':'VALIDATING','reason':None}
            reserved=True
            self.progress.start('RESTORE')
            def work():
                try:
                    self._validate_locked(name)
                except Exception:
                    # The validator persists failure and history. No exception
                    # payload or server traceback is exposed to the browser.
                    pass
                finally:
                    guard.__exit__(None,None,None)
            worker=threading.Thread(target=work,name='pcc-archive-validation',daemon=False)
            worker.start()
            return worker
        except BaseException:
            try:
                if reserved:
                    with self.store.transaction() as operation:
                        operation.phase=Phase.FAILED
                        operation.validation_details={'archive':name,'status':'FAILED',
                            'reason':'Validation could not be started'}
                    try: self.progress.update('FAILED')
                    except ValueError: pass
            finally:
                guard.__exit__(None,None,None)
            raise

    def _validate_locked(self, name):
        """Caller owns the process-wide lock and has committed VALIDATING."""
        try:
            self.progress.start('RESTORE')
            # Keep both directory and source file open. Validation uses the
            # held inode, not a path which an SMB client could replace.
            directory=os.open(self.archive_directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):
                        raise InvalidArchive('Archive must be a regular file')
                    identity=file_identity(os.fstat(fd))
                    result=validate_archive(None, source_fd=fd,
                        progress_callback=lambda stage,done: self.progress.update(stage,done=done))
                    if file_identity(os.fstat(fd))!=identity:
                        raise InvalidArchive('Archive changed during validation')
                finally:
                    os.close(fd)
            finally:
                os.close(directory)
            with self.store.transaction() as operation:
                operation.archive_validated(result.sha256)
                operation.validation_details={'archive':name,'status':'VALID','reason':None,
                    'sha256':result.sha256,'files':result.files,'bytes_read':result.bytes_read,
                    'file_identity':identity}
            self.progress.update('WAITING_FOR_PLEX_STOP')
            self.history.add('ARCHIVE_VALIDATION','SUCCESS',
                             'Archive contents verified; waiting for manual Plex stop.',name)
            return {'archive':name,'sha256':result.sha256,'files':result.files,
                    'bytes_read':result.bytes_read,'phase':'WAITING_FOR_PLEX_STOP'}
        except Exception as error:
            # Only archive-validator messages are safe to show verbatim. OS
            # exceptions can contain host paths; unexpected errors can contain secrets.
            reason=(str(error) if isinstance(error,InvalidArchive) else
                    'Archive is unavailable or unreadable' if isinstance(error,OSError) else
                    'Archive validation could not be completed')
            try: self.progress.update('FAILED')
            except ValueError: pass
            with self.store.transaction() as operation:
                if operation.phase==Phase.VALIDATING:
                    operation.phase=Phase.FAILED
                operation.validation_details={'archive':name,'status':'FAILED','reason':reason}
            self.history.add('ARCHIVE_VALIDATION','FAILED',
                             reason+'. Plex configuration was not modified.',name)
            raise

    def cancel(self):
        with operation_lock(self.state_directory):
            with self.store.transaction() as operation:
                if (operation.kind!='RESTORE' or operation.snapshot_id
                        or operation.phase not in (Phase.WAITING_FOR_PLEX_STOP,Phase.READY)):
                    raise OperationDenied('Cannot cancel an active restore')
                operation.phase=Phase.IDLE
                operation.kind=None
                operation.archive_identity=None
                operation.validation_details=None
            try: self.progress.update('CANCELLED')
            except ValueError: pass
