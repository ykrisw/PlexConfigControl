"""Restore prevalidation without stopping Plex or changing its configuration."""
import os
import stat
from pathlib import Path
from .archive_store import NAME
from .archives import validate_archive
from .locking import operation_lock
from .operations import Phase, OperationDenied
from .publication_intent import pending

class RestoreValidation:
    def __init__(self, archive_directory, state_directory, store, history):
        self.archive_directory=Path(archive_directory)
        self.state_directory=state_directory
        self.store=store
        self.history=history

    def validate(self, name):
        if not isinstance(name,str) or not NAME.fullmatch(name):
            raise ValueError('Choose a recognized backup archive')
        with operation_lock(self.state_directory):
            if pending(self.state_directory):
                raise OperationDenied('Unresolved archive publication requires recovery')
            with self.store.transaction() as operation:
                operation.begin('RESTORE')
            try:
                # Keep both directory and source file open. Validation uses the
                # held inode, not a path which an SMB client could replace.
                directory=os.open(self.archive_directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                try:
                    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
                    try:
                        if not stat.S_ISREG(os.fstat(fd).st_mode):
                            raise ValueError('Archive must be a regular file')
                        result=validate_archive(None, source_fd=fd)
                    finally:
                        os.close(fd)
                finally:
                    os.close(directory)
                with self.store.transaction() as operation:
                    operation.archive_validated(result.sha256)
                self.history.add('ARCHIVE_VALIDATION','SUCCESS',
                                 'Archive contents verified; waiting for manual Plex stop.',name)
                return {'archive':name,'sha256':result.sha256,'files':result.files,
                        'bytes_read':result.bytes_read,'phase':'WAITING_FOR_PLEX_STOP'}
            except Exception:
                with self.store.transaction() as operation:
                    if operation.phase==Phase.VALIDATING:
                        operation.phase=Phase.FAILED
                self.history.add('ARCHIVE_VALIDATION','FAILED',
                                 'Archive validation failed. Plex configuration was not modified.',name)
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
