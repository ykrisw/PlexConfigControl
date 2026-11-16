"""Developer-only test of one freshly owned QNAP snapshot; never a restore.

Not a production coordinator: ownership intent is in memory, with a requested
15-minute vendor expiry as interruption fallback. A packaged worker will need
durable intent in its private state. No supplied QNAP executable is bundled.
"""
import os
import re
import stat
import subprocess
import time
import uuid
from pathlib import Path, PurePosixPath

from .qnap_api import QnapApiError


class SnapshotProbeError(RuntimeError):
    pass


def storage_snapshots(installation, runner=subprocess.run):
    dataset = installation.dataset
    if (not re.fullmatch(r'[A-Za-z0-9_.:/-]+', dataset)
            or any(part in ('', '.', '..') for part in dataset.split('/'))):
        raise SnapshotProbeError('PROBE_INVALID_DATASET')
    result = runner(['/sbin/zfs', 'list', '-H', '-t', 'snapshot', '-o', 'name', '-r', dataset],
                    capture_output=True, text=True, timeout=15, check=False)
    if result.returncode != 0:
        raise SnapshotProbeError('PROBE_STORAGE_QUERY_FAILED')
    found = set()
    for line in result.stdout.splitlines():
        if line.startswith(dataset+'@'):
            if not line[len(dataset)+1:] or any(ord(c) < 32 for c in line):
                raise SnapshotProbeError('PROBE_STORAGE_QUERY_INVALID')
            found.add(line)
        elif line and not line.startswith(dataset+'/'):
            raise SnapshotProbeError('PROBE_STORAGE_QUERY_OUTSIDE_SCOPE')
    return found


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


def inspect_snapshot_data(installation, snapshot_id, baseline, runner=subprocess.run, report=None):
    """Mount the owned snapshot and inspect only file metadata through held fds."""
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
        return source
    finally:
        for fd in reversed(handles):
            os.close(fd)


class OwnedSnapshotProbe:
    def __init__(self, api, installation, *, read_storage=None, inspect_data=None,
                 pause=time.sleep, clock=time.monotonic, report=None):
        self.api, self.installation = api, installation
        self.read_storage = read_storage or (lambda: storage_snapshots(installation))
        self.inspect_data = inspect_data or (lambda identifier, baseline: inspect_snapshot_data(
            installation, identifier, baseline, report=self.report))
        self.pause, self.clock = pause, clock
        self.report = report or (lambda stage, value: None)
        self.name = 'pcc-probe-'+uuid.uuid4().hex
        self.identifier = None
        self.storage_identifier = None
        self.attempted = False
        self.delete_requested = False
        self.baseline_ids = set()
        self.baseline_storage = set()

    def _owned_row(self):
        rows = self.api.snapshots(self.installation.volume_id)
        matches = [row for row in rows if row['name'] == self.name]
        if len(matches) > 1:
            raise SnapshotProbeError('PROBE_OWNERSHIP_AMBIGUOUS')
        if self.identifier is not None and any(
                row['id'] == self.identifier and row['name'] != self.name for row in rows):
            raise SnapshotProbeError('PROBE_SNAPSHOT_IDENTITY_CHANGED')
        if not matches:
            return None
        row = matches[0]
        if row['id'] in self.baseline_ids or (self.identifier is not None and row['id'] != self.identifier):
            raise SnapshotProbeError('PROBE_SNAPSHOT_IDENTITY_CHANGED')
        return row

    def _wait(self, condition, *, seconds=60, stage=None):
        deadline = self.clock()+seconds
        for attempt in range(seconds):
            value = condition()
            if value:
                return value
            if self.clock() >= deadline:
                break
            if stage and attempt % 15 == 0:
                self.report(stage, self.identifier or self.name)
            self.pause(1)
        raise SnapshotProbeError('PROBE_CONFIRMATION_TIMEOUT')

    def _change(self, function):
        session = self.api._session
        if not isinstance(session, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', session):
            raise SnapshotProbeError('PROBE_AUTHENTICATED_SESSION_REQUIRED')
        if function == 'create_snapshot':
            if self.attempted:
                raise SnapshotProbeError('PROBE_CREATE_ALREADY_ATTEMPTED')
            fields = {'func': function, 'volumeID': str(self.installation.volume_id),
                      'snapshot_name': self.name, 'expire_min': '15', 'vital': '0',
                      'snapshot_description': 'PlexConfigControl compatibility test', 'sid': session}
            self.attempted = True  # Never blindly repeat a timed-out create.
        elif function == 'del_snapshots':
            if self.identifier is None or self.delete_requested or self._owned_row() is None:
                raise SnapshotProbeError('PROBE_DELETE_NOT_OWNED_OR_ALREADY_REQUESTED')
            fields = {'func': function, 'snapshotID': self.identifier, 'sid': session}
            self.delete_requested = True
        else:
            raise SnapshotProbeError('PROBE_MUTATION_NOT_ALLOWED')
        root = self.api._exchange_xml('GET', '/cgi-bin/disk/snapshot.cgi', fields)
        result = root.findtext('result', '').strip()
        allowed_results = {'0'}
        if function == 'create_snapshot':
            # The native create handler returns the newly created numeric ID,
            # unlike inventory/delete handlers that return zero. Accept it
            # only when it matches the echoed identity, then confirm inventory.
            info = root.find('SnapshotInfo')
            if info is not None:
                identifier = info.findtext('snapshot_id', '').strip()
                if (re.fullmatch(r'[1-9][0-9]{0,19}', identifier)
                        and info.findtext('snapshot_name') == self.name
                        and identifier not in self.baseline_ids):
                    allowed_results.add(identifier)
        if root.findtext('authPassed') != '1' or result not in allowed_results:
            raise SnapshotProbeError('PROBE_MUTATION_RESPONSE_UNVERIFIED')
        return root

    def _cleanup(self):
        # An absent list immediately after an uncertain create is not proof of
        # cleanup: the vendor may still be creating the snapshot in background.
        # Recover the nonce-bound identity, or explicitly report uncertainty.
        row = self._wait(self._owned_row)
        if self.identifier is None:
            self.identifier = row['id']
        if not self.delete_requested:
            try:
                self._change('del_snapshots')
            except QnapApiError:
                # A lost acknowledgement may still have queued the deletion.
                # Observe both inventories; never send the delete twice.
                if not self.delete_requested:
                    raise
        def absent():
            if self._owned_row() is not None:
                return False
            storage = self.read_storage()
            return (self.storage_identifier not in storage if self.storage_identifier is not None
                    else not storage-self.baseline_storage)
        self._wait(absent, seconds=180, stage='WAITING_FOR_DELETION')
        self.report('CLEANUP_CONFIRMED', self.identifier or self.name)

    def run(self):
        outcome = {'name': self.name, 'created': False, 'readable': False,
                   'cleanup_confirmed': False, 'error': None, 'cleanup_error': None}
        def safe_error(error):
            return str(error) if isinstance(error, (SnapshotProbeError, QnapApiError)) else type(error).__name__
        try:
            rows = self.api.snapshots(self.installation.volume_id)
            if len(rows) != self.api.snapshot_count(self.installation.volume_id) or len(rows) >= 99:
                raise SnapshotProbeError('PROBE_BASELINE_INCOMPLETE')
            self.baseline_ids = {row['id'] for row in rows}
            self.baseline_storage = self.read_storage()
            self.report('CREATING', self.name)
            reply = self._change('create_snapshot')
            info = reply.find('SnapshotInfo')
            if info is not None and info.findtext('snapshot_id') is not None:
                identifier = info.findtext('snapshot_id', '')
                if (not re.fullmatch(r'[1-9][0-9]{0,19}', identifier)
                        or info.findtext('snapshot_name') != self.name or identifier in self.baseline_ids):
                    raise SnapshotProbeError('PROBE_CREATE_IDENTITY_MISMATCH')
                self.identifier = identifier
            row = self._wait(self._owned_row)
            self.identifier = row['id']
            outcome['created'] = True
            self.report('CREATED', self.identifier)
            source = self.inspect_data(self.identifier, self.baseline_storage)
            if not source.startswith(self.installation.dataset+'@') or source in self.baseline_storage:
                raise SnapshotProbeError('PROBE_SNAPSHOT_STORAGE_IDENTITY_MISMATCH')
            self.storage_identifier = source
            outcome['readable'] = True
            self.report('READ_ONLY_PLEX_DATA_CONFIRMED', self.identifier)
        except (Exception, KeyboardInterrupt) as error:
            outcome['error'] = safe_error(error)
        finally:
            if self.attempted:
                try:
                    self._cleanup()
                    outcome['cleanup_confirmed'] = True
                except (Exception, KeyboardInterrupt) as error:
                    outcome['cleanup_error'] = safe_error(error)
        outcome['id'] = self.identifier
        outcome['storage_id'] = self.storage_identifier
        return outcome
