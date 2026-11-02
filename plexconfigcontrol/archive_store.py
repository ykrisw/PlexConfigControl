"""Archive listing and confirmed deletion confined to the backup directory."""
import os
import re
import stat
from dataclasses import dataclass
from .locking import operation_lock

NAME = re.compile(r'TrueNASPlexConfig_\d{4}\.\d{2}\.\d{2}_\d{2}\.\d{2}\.\d{2}\.tar\.gz\Z')

@dataclass(frozen=True)
class Archive:
    name: str
    size: int
    device: int
    inode: int
    modified_ns: int

class ArchiveChanged(RuntimeError):
    pass

class ArchiveStore:
    def __init__(self, directory, state_directory):
        self.directory = directory
        self.state_directory = state_directory

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
                if stat.S_ISREG(info.st_mode):
                    result.append(Archive(name, info.st_size, info.st_dev,
                                          info.st_ino, info.st_mtime_ns))
            return sorted(result, key=lambda item: item.name, reverse=True)
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
        with operation_lock(self.state_directory):
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
