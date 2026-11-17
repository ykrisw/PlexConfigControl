"""Confined first-install output setup; no adoption or permission repair."""
import os
import errno
import stat
from dataclasses import dataclass
from pathlib import Path
from .naming import DEFAULT_FOLDER, folder_component

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class RenameRequired(FileExistsError):
    """Retry only after the user manually renames the existing entry."""
    code = 'RENAME_REQUIRED'


class UnsafeDestination(ValueError):
    code = 'UNSAFE_DESTINATION'


class DestinationChanged(RuntimeError):
    code = 'DESTINATION_CHANGED'


class SetupIncomplete(OSError):
    code = 'SETUP_INCOMPLETE'


@dataclass(frozen=True)
class Destination:
    root: Path
    logs: Path
    device: int
    inode: int
    logs_device: int
    logs_inode: int


def _absolute(value):
    try:
        raw = os.fspath(value)
    except TypeError as error:
        raise UnsafeDestination('Select an existing absolute destination directory') from error
    if not isinstance(raw,str) or '\0' in raw:
        raise UnsafeDestination('Select an existing absolute destination directory')
    path = Path(raw)
    if not path.is_absolute() or path.anchor != '/' or '..' in path.parts or path == Path('/'):
        raise UnsafeDestination('Select an existing absolute destination directory')
    return path


def _parent(parent, forbidden_paths, folder_name=DEFAULT_FOLDER):
    parent = _absolute(parent)
    folder_name=folder_component(folder_name)
    target = parent / folder_name
    for forbidden in forbidden_paths:
        forbidden = _absolute(forbidden)
        if target == forbidden or target in forbidden.parents or forbidden in target.parents:
            raise UnsafeDestination('Output overlaps protected application or Plex storage')
    # NOFOLLOW on the final parent alone would still follow ancestor symlinks.
    fd = os.open('/', FLAGS)
    try:
        for component in parent.parts[1:]:
            child = os.open(component, FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        return parent, fd
    except BaseException:
        os.close(fd)
        raise


def inspect_destination(parent, *, forbidden_paths=(), folder_name=DEFAULT_FOLDER):
    """Read-only setup preflight for a trusted installation-selected parent.

    Name availability is not a write/SMB permission check. Actual creation must
    recheck atomically; do not use this result to authorize adopting a folder.
    """
    parent, fd = _parent(parent, forbidden_paths, folder_name)
    try:
        try:
            os.stat(folder_name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return {'status': 'NAME_AVAILABLE', 'permission_check': 'NOT_TESTED'}
        return {'status': 'RENAME_REQUIRED', 'permission_check': 'NOT_TESTED'}
    finally:
        os.close(fd)


def _same(parent_fd, name, held_fd):
    held = os.fstat(held_fd)
    current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (not stat.S_ISDIR(current.st_mode)
            or (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino)):
        raise DestinationChanged('Destination directory changed during setup or access')
    return held


def _bound_parent(path, held_fd):
    _, current_fd = _parent(path, ())
    try:
        held, current = os.fstat(held_fd), os.fstat(current_fd)
        if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
            raise DestinationChanged('Destination parent path was replaced')
    finally:
        os.close(current_fd)


def create_destination(parent, *, forbidden_paths=(), folder_name=DEFAULT_FOLDER):
    """NEW-install operation, never a restart-time mkdir or an adoption step.

    Deployment supplies protected ixVolume/Plex source paths. Existing entries
    are never renamed, removed, chmodded or chowned. New modes honor process
    umask and inherited ACLs. Keep SMB/external directory changes paused during
    setup: the app lock cannot serialize external rename/mount operations.
    """
    parent, parent_fd = _parent(parent, forbidden_paths, folder_name)
    root_fd = logs_fd = None
    created = False
    try:
        try:
            os.mkdir(folder_name, mode=0o777, dir_fd=parent_fd)
        except FileExistsError as error:
            raise RenameRequired(
                'The selected backup folder already exists. Rename it manually, then retry setup. '
                'Its contents and permissions have not been changed.'
            ) from error
        created = True
        os.fsync(parent_fd)
        root_fd = os.open(folder_name, FLAGS, dir_fd=parent_fd)
        identity = _same(parent_fd, folder_name, root_fd)
        if identity.st_dev != os.fstat(parent_fd).st_dev:
            raise DestinationChanged('New output directory crossed a filesystem boundary')
        os.mkdir('Logs', mode=0o777, dir_fd=root_fd)
        os.fsync(root_fd)
        logs_fd = os.open('Logs', FLAGS, dir_fd=root_fd)
        logs_identity = _same(root_fd, 'Logs', logs_fd)
        if logs_identity.st_dev != identity.st_dev:
            raise DestinationChanged('New Logs directory crossed a filesystem boundary')
        _same(parent_fd, folder_name, root_fd)
        _bound_parent(parent, parent_fd)
        os.fsync(parent_fd)
        return Destination(parent/folder_name, parent/folder_name/'Logs',
                           identity.st_dev, identity.st_ino,
                           logs_identity.st_dev, logs_identity.st_ino)
    except (OSError, DestinationChanged) as error:
        if not created:
            raise
        # SMB may have written into either folder already. No recursive or
        # even empty-directory removal is justified by this exception.
        raise SetupIncomplete(
            getattr(error, 'errno', None),
            'Destination setup could not be confirmed. Existing files were not '
            'removed. Inspect and manually rename the new backup folder '
            'before retrying; check access without resetting ACLs.'
        ) from error
    finally:
        if logs_fd is not None:
            os.close(logs_fd)
        if root_fd is not None:
            os.close(root_fd)
        os.close(parent_fd)


def verify_destination(destination):
    """Read-only runtime identity check, never recreate missing directories.

    Device/inode anchors describe a particular mount session. Deployment must
    establish trusted persistent storage provenance across remounts/reboots;
    these values alone are not a persistent ZFS dataset identifier.
    """
    root = _absolute(destination.root)
    folder_name=folder_component(root.name)
    if destination.logs != root/'Logs':
        raise DestinationChanged('Unexpected configured destination paths')
    parent, parent_fd = _parent(root.parent, (), folder_name)
    root_fd = logs_fd = None
    try:
        root_fd = os.open(folder_name, FLAGS, dir_fd=parent_fd)
        identity = _same(parent_fd, folder_name, root_fd)
        if (identity.st_dev, identity.st_ino) != (destination.device, destination.inode):
            raise DestinationChanged('Configured backup directory was replaced')
        logs_fd = os.open('Logs', FLAGS, dir_fd=root_fd)
        logs_identity = _same(root_fd, 'Logs', logs_fd)
        if (logs_identity.st_dev, logs_identity.st_ino) != (destination.logs_device, destination.logs_inode):
            raise DestinationChanged('Configured Logs directory was replaced')
        _same(parent_fd, folder_name, root_fd)
        _bound_parent(parent, parent_fd)
        return True
    finally:
        if logs_fd is not None:
            os.close(logs_fd)
        if root_fd is not None:
            os.close(root_fd)
        os.close(parent_fd)


def describe_setup_error(error, language='en'):
    """Safe installer-facing diagnostics, never arbitrary OS exception text."""
    from .i18n import translate
    if isinstance(error, RenameRequired):
        code,key='RENAME_REQUIRED','rename_folder'
    elif isinstance(error, SetupIncomplete):
        code,key='SETUP_INCOMPLETE','setup_incomplete'
    elif isinstance(error, DestinationChanged):
        code,key='DESTINATION_CHANGED','destination_changed'
    elif isinstance(error, UnsafeDestination) or (isinstance(error,OSError) and error.errno in (errno.ELOOP,errno.ENOTDIR)):
        code,key='UNSAFE_DESTINATION','unsafe_destination'
    elif isinstance(error, PermissionError):
        code,key='ACCESS_REQUIRED','setup_access_required'
    elif isinstance(error, FileNotFoundError):
        code,key='PARENT_UNAVAILABLE','setup_parent_unavailable'
    else:
        code,key='SETUP_FAILED','setup_failed'
    return {'code':code,'message':translate(key,language)}
