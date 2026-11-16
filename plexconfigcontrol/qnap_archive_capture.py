"""Create a private portable archive from a held, verified QNAP snapshot fd.

This is an archive component, not a production backup coordinator. The owner
must hold its operation lock, maintain durable snapshot intent, and keep the
reader context open. This module never creates/deletes snapshots, publishes an
archive, stops Plex, or writes to its live configuration.
"""
import os
from pathlib import Path
import re
import stat
import subprocess

from .backup_archive import BackupArchiveError, create_archive
from .qnap_snapshot_reader import QnapSnapshotSource


class QnapArchiveCaptureError(BackupArchiveError):
    pass


def capture_snapshot_archive(source, output, private_tar, *, verification_progress=None,
                             runner=subprocess.run):
    if (type(source) is not QnapSnapshotSource or type(source.descriptor) is not int
            or source.descriptor < 0 or not isinstance(source.storage_identity, str)
            or not re.fullmatch(r'[A-Za-z0-9_.:/-]+@[^/\x00-\x1f]+', source.storage_identity)):
        raise QnapArchiveCaptureError('Verified QNAP snapshot source required')
    before = os.fstat(source.descriptor)
    if not stat.S_ISDIR(before.st_mode) or not os.statvfs(source.descriptor).f_flag & os.ST_RDONLY:
        raise QnapArchiveCaptureError('Snapshot directory must remain read-only')
    binary = Path(private_tar)
    if (not binary.is_absolute() or binary.is_symlink() or not binary.is_file()
            or binary.stat().st_mode & 0o022 or not os.access(binary, os.X_OK)):
        raise QnapArchiveCaptureError('Explicit trusted archive executable required')
    output = Path(output)
    parent = output.parent
    if parent.is_symlink() or not parent.is_dir():
        raise QnapArchiveCaptureError('Private archive workspace required')
    info = parent.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise QnapArchiveCaptureError('Archive workspace must be private to the worker')

    def run_tar(argv, **options):
        # The subprocess must inherit the held fd: its /proc/self/fd path then
        # names the same snapshot directory, rather than re-resolving NAS paths.
        return runner(argv, pass_fds=(source.descriptor,), **options)

    created = False
    try:
        result = create_archive('/proc/self/fd/'+str(source.descriptor), output,
            source_layout='plex-data', tar_executable=str(binary), all_xattrs=True,
            tar_runner=run_tar, verification_progress=verification_progress)
        created = True
        after = os.fstat(source.descriptor)
        if ((before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
                or not os.statvfs(source.descriptor).f_flag & os.ST_RDONLY):
            raise QnapArchiveCaptureError('Snapshot directory identity changed')
        return result
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise
