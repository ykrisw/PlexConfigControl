"""Archive listing and confirmed deletion confined to the backup directory."""
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from .locking import operation_lock, OperationBusy
from .operations import Phase
from .state import StateStore

from .naming import ARCHIVE_NAME as NAME, ARCHIVE_TIMESTAMP

@dataclass(frozen=True)
class Archive:
    name: str
    size: int
    device: int
    inode: int
    modified_ns: int

class ArchiveChanged(RuntimeError):
    pass

def file_identity(info):
    return {'device':info.st_dev,'inode':info.st_ino,'size':info.st_size,
            'modified_ns':info.st_mtime_ns,'changed_ns':info.st_ctime_ns}

def archive_matches(directory,name,identity):
    """Cheap advisory check; full digest verification is still required at use."""
    if directory is None or not isinstance(name,str) or not NAME.fullmatch(name):
        return False
    try:
        fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            info=os.stat(name,dir_fd=fd,follow_symlinks=False)
            return stat.S_ISREG(info.st_mode) and file_identity(info)==identity
        finally:
            os.close(fd)
    except OSError:
        return False

class ArchiveStore:
    def __init__(self, directory, state_directory):
        self.directory = directory
        self.state_directory = state_directory
        self.state = StateStore(state_directory)

    def _open(self):
        return os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def list(self):
        fd = self._open()
        try:
            result = []
            for name in os.listdir(fd):
                if not NAME.fullmatch(name):
                    continue
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if stat.S_ISREG(info.st_mode) and (ARCHIVE_TIMESTAMP.search(name) or self._looks_gzipped(fd, name)):
                    result.append(Archive(name, info.st_size, info.st_dev,
                                          info.st_ino, info.st_mtime_ns))
            # The embedded timestamp survives copies. For renamed archives
            # without one, use the file modification date in the same timezone.
            zone = ZoneInfo('Europe/London')

            def newest_first(item):
                timestamp = ARCHIVE_TIMESTAMP.search(item.name)
                stamp = timestamp[1] if timestamp else datetime.fromtimestamp(
                    item.modified_ns // 1_000_000_000, zone).strftime('%Y.%m.%d_%H.%M.%S')
                return stamp, item.modified_ns, item.name

            return sorted(result, key=newest_first, reverse=True)
        finally:
            os.close(fd)

    @staticmethod
    def _looks_gzipped(directory_fd, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        except OSError:
            return False
        try:
            return stat.S_ISREG(os.fstat(fd).st_mode) and os.read(fd, 3) == b'\x1f\x8b\x08'
        finally:
            os.close(fd)

    def delete(self, selected, confirmed=False):
        """Require the exact listing identities shown in the confirmation dialog.

        An authenticated CSRF-protected web route must call this method. The
        operation lock excludes app-managed restore/backup, not external SMB
        writers; external changes detected before unlink abort the request.
        """
        if confirmed is not True or not selected:
            raise ValueError('Select archives and explicitly confirm deletion')
        if len({item.name for item in selected}) != len(selected):
            raise ValueError('Duplicate selection')
        from .publication_intent import pending
        with operation_lock(self.state_directory):
            if pending(self.state_directory):
                raise OperationBusy('Archive publication requires recovery before deletion')
            with self.state.transaction() as operation:
                if operation.snapshot_id or operation.phase not in (Phase.IDLE,Phase.SUCCESS,Phase.FAILED):
                    raise OperationBusy('Operation or recovery must finish before archive deletion')
            fd = self._open()
            try:
                for item in selected:
                    self._verify(fd, item)
                removed = []
                for item in selected:
                    self._verify(fd, item)
                    os.unlink(item.name, dir_fd=fd)
                    os.fsync(fd)
                    removed.append(item.name)
                return removed
            finally:
                os.close(fd)

    @staticmethod
    def _verify(fd, item):
        if not NAME.fullmatch(item.name):
            raise ValueError('Not an application archive name')
        info = os.stat(item.name, dir_fd=fd, follow_symlinks=False)
        current = Archive(item.name, info.st_size, info.st_dev,
                          info.st_ino, info.st_mtime_ns)
        if not stat.S_ISREG(info.st_mode) or current != item:
            raise ArchiveChanged('Selected archive changed; refresh and confirm again')
