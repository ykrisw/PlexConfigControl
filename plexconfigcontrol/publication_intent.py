"""Durable publication marker in the private ixVolume; caller holds operation lock."""
import os
import json
import re
import stat
from .archive_store import NAME

MARKER = 'publication-intent.txt'
REPLACEMENT_MARKER = 'replacement-intent.json'

def record(directory, stage, archive, sha256=None):
    if not re.fullmatch(r'\.pcc-[0-9a-f]{32}\.tmp', stage) or not NAME.fullmatch(archive):
        raise ValueError('Invalid publication identity')
    if sha256 is not None and (not isinstance(sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', sha256)):
        raise ValueError('Invalid publication digest')
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # Never truncate an outstanding record, including one from a failed run.
        fd = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, 'w') as output:
            output.write(stage + '\n' + archive + '\n' + (sha256 + '\n' if sha256 is not None else ''))
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
    return any(os.path.lexists(os.path.join(directory, name))
               for name in (MARKER, REPLACEMENT_MARKER))

def describe(directory):
    """Read-only diagnostic; never treat a marker as proof of archive success.

    Corrupt, oversized, special or inaccessible records remain blocked. Do not
    return arbitrary marker contents, which may contain paths or other data.
    """
    blocked = {'pending': True, 'status': 'RECORD_UNREADABLE',
               'archive': None, 'temporary_file': None}
    if os.path.lexists(os.path.join(directory, REPLACEMENT_MARKER)):
        try:
            if os.path.lexists(os.path.join(directory, MARKER)):
                return blocked
            item = read_replacement(directory)
            return {'pending': True, 'status': 'VERIFICATION_REQUIRED',
                    'archive': item['archive'], 'temporary_file': item['stage'],
                    'replaced_archive': item['original']}
        except (OSError, ValueError, UnicodeError):
            return blocked
    try:
        item = read(directory)
        return {'pending': True, 'status': 'VERIFICATION_REQUIRED',
                'archive': item['archive'], 'temporary_file': item['stage']}
    except FileNotFoundError:
        if os.path.lexists(os.path.join(directory, MARKER)):
            return blocked
        return {'pending': False, 'status': 'NONE',
                'archive': None, 'temporary_file': None}
    except (OSError, ValueError, UnicodeError):
        return blocked


def read(directory):
    """Accept old two-line records for diagnosis, without inventing a digest."""
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 512:
                raise ValueError('Invalid publication record file')
            payload = source.read(513)
    finally:
        os.close(parent)
    lines = payload.decode('ascii').splitlines()
    if (len(payload) > 512 or len(lines) not in (2, 3)
            or not re.fullmatch(r'\.pcc-[0-9a-f]{32}\.tmp', lines[0])
            or not NAME.fullmatch(lines[1])
            or (len(lines) == 3 and not re.fullmatch(r'[0-9a-f]{64}', lines[2]))):
        raise ValueError('Invalid publication identity')
    return {'stage': lines[0], 'archive': lines[1],
            'sha256': lines[2] if len(lines) == 3 else None}


def _validate_replacement(item):
    if not isinstance(item, dict) or set(item) != {
            'version', 'stage', 'archive', 'sha256', 'original', 'identity'}:
        raise ValueError('Invalid replacement record')
    identity = item['identity']
    if (type(item['version']) is not int or item['version'] != 1
            or not isinstance(item['stage'], str)
            or not re.fullmatch(r'\.pcc-[0-9a-f]{32}\.tmp', item['stage'])
            or any(not isinstance(item[key], str) or not NAME.fullmatch(item[key])
                   for key in ('archive', 'original'))
            or item['archive'] == item['original']
            or not isinstance(item['sha256'], str)
            or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])
            or not isinstance(identity, dict)
            or set(identity) != {'device', 'inode', 'size', 'modified_ns', 'changed_ns'}
            or any(type(value) is not int or value < 0 for value in identity.values())):
        raise ValueError('Invalid replacement identity')
    return item


def record_replacement(directory, stage, archive, digest, original, identity):
    item = _validate_replacement({'version': 1, 'stage': stage, 'archive': archive,
                                 'sha256': digest, 'original': original,
                                 'identity': identity})
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(REPLACEMENT_MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'w') as output:
            json.dump(item, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.fsync(parent)
    finally:
        os.close(parent)


def read_replacement(directory):
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(REPLACEMENT_MARKER, os.O_RDONLY | os.O_NOFOLLOW
                     | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 2048:
                raise ValueError('Invalid replacement record file')
            payload = source.read(2049)
    finally:
        os.close(parent)
    if len(payload) > 2048:
        raise ValueError('Oversized replacement record')
    return _validate_replacement(json.loads(payload))


def clear_replacement(directory):
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.unlink(REPLACEMENT_MARKER, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)
