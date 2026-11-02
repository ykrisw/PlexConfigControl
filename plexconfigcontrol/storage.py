"""First-install destination creation without adopting existing user folders."""
import errno
import os
from dataclasses import dataclass
from pathlib import Path


class RenameRequired(FileExistsError):
    """Surface this message in setup; retry only after the user renames it."""


@dataclass(frozen=True)
class Destination:
    root: Path
    logs: Path
    device: int
    inode: int


def create_destination(parent):
    """Call only for a NEW installation, not each application/container restart.

    The installation coordinator must persist the returned directory identity in
    ixVolume and verify it on subsequent starts. Existing directories, files and
    symlinks are never adopted, renamed, chmodded, chowned or removed here.
    No exist_ok and no recursive cleanup of user-controlled paths are permitted.
    Parent must already exist and have the intended user/SMB ACL inheritance.
    """
    parent = Path(parent)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent_fd = os.open(parent, flags)
    root_fd = None
    try:
        try:
            os.mkdir('Plex Config', mode=0o777, dir_fd=parent_fd)
        except FileExistsError as error:
            raise RenameRequired(
                'Plex Config already exists. Rename it manually, then retry setup. '
                'Its contents and permissions have not been changed.'
            ) from error
        root_fd = os.open('Plex Config', flags, dir_fd=parent_fd)
        identity = os.fstat(root_fd)
        try:
            os.mkdir('Logs', mode=0o777, dir_fd=root_fd)
        except OSError as error:
            # Keep the directory visible for explicit user recovery; never
            # recursively delete a folder into which SMB may already have written.
            raise OSError(
                error.errno,
                'Could not create Logs. Rename the new Plex Config folder and '
                'check destination write access before retrying setup.'
            ) from error
        return Destination(parent / 'Plex Config', parent / 'Plex Config' / 'Logs',
                           identity.st_dev, identity.st_ino)
    finally:
        if root_fd is not None:
            os.close(root_fd)
        os.close(parent_fd)
