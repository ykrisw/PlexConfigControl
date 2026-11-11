"""Read-only QNAP package/storage discovery. No host mutation or restore commands."""
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class QnapDiscoveryError(ValueError):
    pass


@dataclass(frozen=True)
class QnapPlexInstallation:
    package_version: str
    package_enabled: bool
    install_directory: str
    data_directory: str
    dataset: str
    dataset_mount: str
    relative_path: str
    volume_id: int

    @property
    def dedicated_dataset_root(self):
        return self.relative_path == '.'


def _absolute(value):
    if (not isinstance(value, str) or not value.startswith('/share/')
            or '\\' in value or '//' in value
            or any(ord(char) < 32 for char in value)
            or any(part in ('.', '..') for part in value.split('/'))):
        raise QnapDiscoveryError('INVALID_QNAP_PATH')
    return PurePosixPath(value)


def storage_for_path(directory, listing):
    """Select the covering filesystem, excluding every snapshot record."""
    directory = _absolute(directory)
    candidates = []
    for line in listing.splitlines():
        fields = line.split('\t')
        if len(fields) != 2:
            raise QnapDiscoveryError('INVALID_DATASET_LIST')
        dataset, mount = fields
        if '@' in dataset or '#' in dataset or mount in ('-', 'none', 'legacy'):
            continue
        if (not re.fullmatch(r'[A-Za-z0-9_.:/-]+', dataset)
                or any(part in ('', '.', '..') for part in dataset.split('/'))):
            raise QnapDiscoveryError('INVALID_DATASET_NAME')
        if not mount.startswith('/share/'):
            continue
        mount = _absolute(mount)
        if directory == mount or mount in directory.parents:
            candidates.append((len(mount.parts), dataset, str(mount)))
    if not candidates:
        raise QnapDiscoveryError('PLEX_DATASET_NOT_FOUND')
    deepest = max(item[0] for item in candidates)
    matches = {(dataset, mount) for depth, dataset, mount in candidates if depth == deepest}
    if len(matches) != 1:
        raise QnapDiscoveryError('AMBIGUOUS_PLEX_DATASET')
    dataset, mount = matches.pop()
    return dataset, mount, str(directory.relative_to(mount))


def discover_qnap_plex(*, runner=subprocess.run, resolve=None, is_directory=os.path.isdir):
    """Read only selected QPKG fields and filesystem identities.

    Package enablement is deliberately not reported as process readiness.
    QNAP shared-dataset plans must never be fed to the TrueNAS rollback adapter.
    """
    resolve = resolve or (lambda path: str(Path(path).resolve(strict=True)))

    def read(argv):
        try:
            result = runner(argv, capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.SubprocessError):
            raise QnapDiscoveryError('QNAP_DISCOVERY_UNAVAILABLE') from None
        if result.returncode != 0:
            raise QnapDiscoveryError('QNAP_DISCOVERY_ACCESS_REQUIRED')
        return result.stdout.strip()

    def setting(name):
        return read(['/sbin/getcfg', 'PlexMediaServer', name, '-f', '/etc/config/qpkg.conf'])

    install = setting('Install_Path')
    _absolute(install)
    if not re.fullmatch(r'/share/[^/]+/\.qpkg/PlexMediaServer', install):
        raise QnapDiscoveryError('UNSUPPORTED_PLEX_PACKAGE_LOCATION')
    version, enabled = setting('Version'), setting('Enable').upper()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:\.\d+)?(?:-[A-Za-z0-9_.-]+)?', version):
        raise QnapDiscoveryError('INVALID_PLEX_PACKAGE_VERSION')
    if enabled not in ('TRUE', 'FALSE'):
        raise QnapDiscoveryError('INVALID_PACKAGE_ENABLEMENT')
    try:
        actual_install = resolve(install)
        _absolute(actual_install)
        data_paths = {
            resolve(path) for path in (install+'/Library/Plex Media Server',
                install+'/Library/Application Support/Plex Media Server') if is_directory(path)
        }
    except OSError:
        raise QnapDiscoveryError('PLEX_DIRECTORY_UNAVAILABLE') from None
    if len(data_paths) != 1:
        raise QnapDiscoveryError('PLEX_DATA_DIRECTORY_NOT_UNIQUE')
    data = data_paths.pop()
    data_path = _absolute(data)
    if PurePosixPath(actual_install) not in data_path.parents:
        raise QnapDiscoveryError('PLEX_DATA_OUTSIDE_PACKAGE')
    dataset, mount, relative = storage_for_path(data, read(
        ['/sbin/zfs', 'list', '-H', '-t', 'filesystem', '-o', 'name,mountpoint']))
    # Native QNAP volume IDs are not ZFS dataset suffixes. Query the exact
    # covering mount; never infer an ID from a pool/dataset/path name.
    volume = read(['/sbin/snapshot_util', 'get_volume_id', mount])
    if not re.fullmatch(r'[1-9][0-9]{0,9}', volume):
        raise QnapDiscoveryError('INVALID_QNAP_VOLUME_ID')
    return QnapPlexInstallation(version, enabled == 'TRUE', actual_install,
        data, dataset, mount, relative, int(volume))
