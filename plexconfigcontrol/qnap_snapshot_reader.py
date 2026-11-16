"""Scoped read-only QNAP snapshot reader. Never creates/deletes/restores snapshots.

The coordinator must supply a proven freshly owned native ID and baseline.
Only native preview mounting and read-only descriptor access occur here.
"""
import os
import re
import stat
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class QnapSnapshotReadError(RuntimeError):
    pass


# Preserve the diagnostic's existing exception/code contract.
SnapshotProbeError = QnapSnapshotReadError


@dataclass(frozen=True)
class QnapSnapshotSource:
    descriptor: int
    storage_identity: str


def snapshot_mount_details(path, mountinfo):
    """Return only the deepest covering mount's metadata, not all NAS mounts."""
    path = PurePosixPath(path)
    candidates = []
    def decode(value):
        return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)
    for line in mountinfo.splitlines():
        left, separator, right = line.partition(' - ')
        fields, filesystem = left.split(), right.split()
        if not separator or len(fields) < 6 or len(filesystem) < 3:
            raise SnapshotProbeError('PROBE_MOUNTINFO_INVALID')
        mount = PurePosixPath(decode(fields[4]))
        if mount == path or mount in path.parents:
            candidates.append((len(mount.parts), fields, filesystem))
    if not candidates:
        raise SnapshotProbeError('PROBE_MOUNT_NOT_IDENTIFIED')
    depth = max(item[0] for item in candidates)
    matches = [item for item in candidates if item[0] == depth]
    if len(matches) != 1:
        raise SnapshotProbeError('PROBE_MOUNT_AMBIGUOUS')
    _, fields, filesystem = matches[0]
    return {'filesystem': filesystem[0], 'source': decode(filesystem[1]),
            'root': decode(fields[3]), 'mount': decode(fields[4]),
            'options': fields[5], 'super_options': filesystem[2]}


def snapshot_mount_source(path, mountinfo, dataset):
    """Identify the deepest covering ZFS snapshot mount, never a live mount."""
    details = snapshot_mount_details(path, mountinfo)
    source = details['source']
    # QuTS hero reports per-mount rw with a read-only ZFS superblock. Either
    # mountinfo layer can establish ro here; the held directory descriptor's
    # ST_RDONLY flag is additionally mandatory before accessing Plex files.
    reported_readonly = ('ro' in details['options'].split(',')
                         or 'ro' in details['super_options'].split(','))
    if (details['filesystem'] != 'zfs' or not reported_readonly
            or not source.startswith(dataset+'@') or not source[len(dataset)+1:]):
        raise SnapshotProbeError('PROBE_MOUNT_NOT_SCOPED_READONLY_SNAPSHOT')
    return source


@contextmanager
def open_snapshot_data(installation, snapshot_id, baseline, runner=subprocess.run, report=None):
    """Mount the owned snapshot and inspect only file metadata through held fds."""
    if not isinstance(snapshot_id, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', snapshot_id):
        raise SnapshotProbeError('PROBE_INVALID_SNAPSHOT_ID')
    result = runner(['/sbin/snapshot_util', 'mount_snapshot', snapshot_id],
                    capture_output=True, text=True, timeout=30, check=False)
    preview = result.stdout.strip()
    if result.returncode != 0 or not preview.startswith(('/share/', '/mnt/snapshot/')) or '\n' in preview:
        raise SnapshotProbeError('PROBE_SNAPSHOT_MOUNT_FAILED')
    root = Path(preview).resolve(strict=True)
    relative = PurePosixPath(installation.relative_path)
    if relative.is_absolute() or any(part in ('.', '..') for part in relative.parts) or not relative.parts:
        raise SnapshotProbeError('PROBE_INVALID_PLEX_SUBTREE')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    handles = []
    try:
        fd = os.open(root, flags)
        handles.append(fd)
        # Opening the preview directory can trigger a lazy snapshot mount.
        # Inspect mountinfo after that access, before opening any Plex files.
        readonly = bool(os.statvfs(fd).f_flag & os.ST_RDONLY)
        mountinfo = Path('/proc/self/mountinfo').read_text()
        if report is not None:
            import json
            details = snapshot_mount_details(str(root), mountinfo)
            details.update(preview=preview, resolved_preview=str(root), vfs_readonly=readonly)
            report('SNAPSHOT_MOUNT_INFO', json.dumps(details, ensure_ascii=True, sort_keys=True))
        source = snapshot_mount_source(str(root), mountinfo, installation.dataset)
        if source in baseline:
            raise SnapshotProbeError('PROBE_MOUNT_POINTS_TO_PREEXISTING_SNAPSHOT')
        if not readonly:
            raise SnapshotProbeError('PROBE_SNAPSHOT_FILESYSTEM_WRITABLE')
        for part in relative.parts:
            fd = os.open(part, flags, dir_fd=fd)
            handles.append(fd)
        if os.fstat(fd).st_dev != os.fstat(handles[0]).st_dev or not os.statvfs(fd).f_flag & os.ST_RDONLY:
            raise SnapshotProbeError('PROBE_PLEX_SUBTREE_FILESYSTEM_CHANGED')
        for parts in (
                ('Preferences.xml',),
                ('Plug-in Support', 'Databases', 'com.plexapp.plugins.library.db'),
                ('Plug-in Support', 'Databases', 'com.plexapp.plugins.library.blobs.db')):
            current = fd
            for part in parts[:-1]:
                current = os.open(part, flags, dir_fd=current)
                handles.append(current)
            file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current)
            handles.append(file_fd)
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
                raise SnapshotProbeError('PROBE_PLEX_SNAPSHOT_FILE_INVALID')
        # No Preferences contents or database contents are read or printed.
        yield QnapSnapshotSource(fd, source)
    finally:
        for fd in reversed(handles):
            os.close(fd)


def inspect_snapshot_data(installation, snapshot_id, baseline, runner=subprocess.run, report=None):
    with open_snapshot_data(installation, snapshot_id, baseline, runner=runner, report=report) as source:
        return source.storage_identity
