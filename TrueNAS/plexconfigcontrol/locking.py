"""Process-wide operation lock, located exclusively in application state storage."""
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

class OperationBusy(RuntimeError):
    pass

@contextmanager
def operation_lock(state_directory):
    """Hold across the complete operation, including network calls and cleanup.

    Never unlink this file: replacing the inode would let another process obtain
    a different lock. The kernel releases the lock if the holder exits/crashes;
    persistent operation state still requires reconciliation after a crash.
    """
    directory = Path(state_directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fd = None
    acquired = False
    try:
        fd = os.open('operation.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                     0o600, dir_fd=dir_fd)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError as error:
            raise OperationBusy('Another operation is already running') from error
        yield
    finally:
        if fd is not None:
            if acquired:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        os.close(dir_fd)
