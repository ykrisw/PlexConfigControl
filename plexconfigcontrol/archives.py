"""Backup naming and read-only archive validation; does not restore data."""
import gzip
import hashlib
import os
import stat
import tarfile
from dataclasses import dataclass
from zoneinfo import ZoneInfo

BASE = 'config/Library/Application Support/Plex Media Server/'
REQUIRED = {BASE + 'Preferences.xml', BASE + 'Plug-in Support/Databases/' + 'com.plexapp.plugins.library.db', BASE + 'Plug-in Support/Databases/' + 'com.plexapp.plugins.library.blobs.db'}

class InvalidArchive(ValueError):
    pass

def backup_action(count):
    if count < 0:
        raise ValueError('Negative archive count')
    return 'ASK_OVERWRITE_OR_NEW' if count == 1 else 'CREATE_NEW'

def archive_name(instant, timezone='Europe/London'):
    if instant.tzinfo is None:
        raise ValueError('Timezone-aware timestamp required')
    return instant.astimezone(ZoneInfo(timezone)).strftime('TrueNASPlexConfig_%Y.%m.%d_%H.%M.%S.tar.gz')

@dataclass(frozen=True)
class Validation:
    sha256: str
    files: int
    bytes_read: int

def validate_archive(path, max_bytes=1024**4, max_members=2_000_000):
    """Reject links/special files conservatively; read all files and gzip trailer.

    Database integrity and metadata checks are separate restore steps.
    Caller must prevent replacement/modification between validation and use.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise InvalidArchive('Regular archive file required')
        names, regular = set(), set()
        total = files = 0
        try:
            with tarfile.open(fileobj=source, mode='r|gz') as archive:
                for index, member in enumerate(archive):
                    name = member.name.rstrip('/')
                    parts = name.split('/')
                    if index >= max_members:
                        raise InvalidArchive('Too many entries')
                    if (name.startswith('/') or parts[0] != 'config' or any(p in ('', '.', '..') for p in parts) or '\\' in name or name in names):
                        raise InvalidArchive('Unsafe or duplicate path')
                    names.add(name)
                    if not (member.isdir() or member.isreg()):
                        raise InvalidArchive('Links and special files unsupported')
                    if member.isreg():
                        if member.size < 0 or total + member.size > max_bytes:
                            raise InvalidArchive('Size limit exceeded')
                        stream = archive.extractfile(member)
                        read = 0
                        while chunk := stream.read(1024 * 1024):
                            read += len(chunk)
                        if read != member.size:
                            raise InvalidArchive('Incomplete file')
                        total += read
                        files += 1
                        regular.add(name)
            if not REQUIRED <= regular:
                raise InvalidArchive('Required Plex files missing')
            source.seek(0)
            expanded = 0
            with gzip.GzipFile(fileobj=source) as compressed:
                while chunk := compressed.read(1024 * 1024):
                    expanded += len(chunk)
                    if expanded > max_bytes + max_members * 4096:
                        raise InvalidArchive('Stream limit exceeded')
            source.seek(0)
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        except (tarfile.TarError, EOFError, OSError) as error:
            raise InvalidArchive('Corrupt or unreadable archive') from error
        after = os.fstat(source.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise InvalidArchive('Archive changed during validation')
        return Validation(digest, files, total)
