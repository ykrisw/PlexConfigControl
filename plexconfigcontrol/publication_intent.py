"""Durable publication marker in the private ixVolume; caller holds operation lock."""
import os
import re
from .archive_store import NAME

MARKER = 'publication-intent.txt'

def record(directory, stage, archive):
    if not re.fullmatch(r'\.pcc-[0-9a-f]{32}\.tmp', stage) or not NAME.fullmatch(archive):
        raise ValueError('Invalid publication identity')
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # Never truncate an outstanding record, including one from a failed run.
        fd = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, 'w') as output:
            output.write(stage + '\n' + archive + '\n')
            output.flush()
            os.fsync(output.fileno())
        # The marker's directory entry must also survive before staging starts.
        os.fsync(parent)
    finally:
        os.close(parent)

def clear(directory):
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.unlink(MARKER, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)

def pending(directory):
    # A malformed file or dangling symlink also blocks work for investigation.
    return os.path.lexists(os.path.join(directory, MARKER))
