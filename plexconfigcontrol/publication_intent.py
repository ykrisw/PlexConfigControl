"""Durable publication marker in the private ixVolume; caller holds operation lock."""
import os
import re
import stat
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

def describe(directory):
    """Read-only diagnostic; never treat a marker as proof of archive success.

    Corrupt, oversized, special or inaccessible records remain blocked. Do not
    return arbitrary marker contents, which may contain paths or other data.
    """
    blocked = {'pending': True, 'status': 'RECORD_UNREADABLE',
               'archive': None, 'temporary_file': None}
    try:
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                fd = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=parent)
            except FileNotFoundError:
                return {'pending': False, 'status': 'NONE',
                        'archive': None, 'temporary_file': None}
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 512:
                    return blocked
                payload = source.read(513)
        finally:
            os.close(parent)
        lines = payload.decode('ascii').splitlines()
        if (len(payload) > 512 or len(lines) != 2 or
                not re.fullmatch(r'\.pcc-[0-9a-f]{32}\.tmp', lines[0]) or
                not NAME.fullmatch(lines[1])):
            return blocked
        return {'pending': True, 'status': 'VERIFICATION_REQUIRED',
                'archive': lines[1], 'temporary_file': lines[0]}
    except (OSError, UnicodeError):
        return blocked
