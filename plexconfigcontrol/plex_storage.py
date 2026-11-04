"""Installation-only Plex storage discovery. No Docker socket or host mutations."""
from dataclasses import dataclass
from pathlib import PurePosixPath


class StorageDiscoveryError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)  # Never include API configuration, tokens or raw errors.


@dataclass(frozen=True)
class PlexStorage:
    storage_type: str
    source: str
    dataset: str
    dataset_mount: str
    relative_path: str

    @property
    def dedicated_dataset_root(self):
        return self.relative_path == '.'


def _path(value):
    if (not isinstance(value,str) or not value.startswith('/mnt/') or '\\' in value
            or any(ord(char)<32 for char in value) or '//' in value
            or any(part in ('.','..') for part in value.split('/'))):
        raise StorageDiscoveryError('INVALID_CONFIG_PATH')
    path = PurePosixPath(value)
    if path == PurePosixPath('/mnt'):
        raise StorageDiscoveryError('INVALID_CONFIG_PATH')
    protected = PurePosixPath('/mnt/TrueNAS/TrueNAS/PBS-Data')
    if path == protected or protected in path.parents:
        raise StorageDiscoveryError('PROTECTED_STORAGE')
    return str(path)


def _setting(config):
    try:
        setting = config['storage']['config']
        kind = setting['type']
        if kind not in ('ix_volume','host_path'):
            raise ValueError()
        if kind == 'host_path':
            host = setting['host_path_config']
            value = host['acl']['path'] if host.get('acl_enable') is True else host['path']
            return kind, _path(value)
        # The actual mount, never a guessed ix-apps path, resolves ixVolume.
        return kind, None
    except StorageDiscoveryError:
        raise
    except (KeyError,TypeError,ValueError):
        raise StorageDiscoveryError('UNSUPPORTED_PLEX_STORAGE_SETTINGS') from None


def _mounts(row):
    try:
        volumes = row['active_workloads']['volumes']
        if not isinstance(volumes,list):raise ValueError()
        matches = [item for item in volumes if isinstance(item,dict) and item.get('destination')=='/config']
        # Dedup identical mount records reported for multiple containers only.
        found = set()
        for item in matches:
            if item.get('type') != 'bind':raise ValueError()
            found.add(_path(item.get('source')))
        if len(found)!=1:raise ValueError()
        return found.pop()
    except StorageDiscoveryError:
        raise
    except (KeyError,TypeError,ValueError):
        raise StorageDiscoveryError('CONFIG_MOUNT_NOT_CONFIRMED') from None


def discover_plex_storage(api, *, manual_source=None):
    """Read settings + actual /config mapping + ZFS identity, then recheck.

    This trusted installer function accepts an API client, never a client-supplied
    dataset. An explicit manual path still has to match the actual /config mount.
    It does not grant the restricted WWW runtime broader reads.
    """
    manual = _path(manual_source) if manual_source is not None else None
    def read():
        if manual is None:
            config = api.call('app.config','plex')
            kind, declared = _setting(config)
        else:
            kind, declared = 'manual', manual
        rows = api.call('app.query', [['name','=','plex']], {'select':['name','state','active_workloads']})
        if (not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict)
                or rows[0].get('name')!='plex'):
            raise StorageDiscoveryError('PLEX_NOT_CONFIRMED')
        if rows[0].get('state') not in ('RUNNING','STOPPED'):
            raise StorageDiscoveryError('PLEX_CONFIGURATION_CHANGING')
        source = _mounts(rows[0])
        if declared is not None and source!=declared:
            raise StorageDiscoveryError('SETTINGS_MOUNT_MISMATCH')
        fs = api.call('filesystem.statfs',source)
        if not isinstance(fs,dict) or fs.get('fstype')!='zfs':
            raise StorageDiscoveryError('CONFIG_NOT_ON_ZFS')
        dataset = fs.get('source')
        if (not isinstance(dataset,str) or not dataset or dataset.startswith('/')
                or any(part in ('','.','..') for part in dataset.split('/'))
                or any(ord(c)<33 for c in dataset) or '@' in dataset or '#' in dataset):
            raise StorageDiscoveryError('INVALID_CONFIG_DATASET')
        if dataset=='TrueNAS/TrueNAS/PBS-Data' or dataset.startswith('TrueNAS/TrueNAS/PBS-Data/'):
            raise StorageDiscoveryError('PROTECTED_STORAGE')
        mount = _path(fs.get('dest'))
        try: relative = str(PurePosixPath(source).relative_to(mount))
        except ValueError:raise StorageDiscoveryError('DATASET_MOUNT_MISMATCH') from None
        return PlexStorage(kind,source,dataset,mount,relative)
    try:
        first=read()
        if read()!=first:raise StorageDiscoveryError('PLEX_STORAGE_CHANGED')
        return first
    except StorageDiscoveryError:
        raise
    except Exception:
        raise StorageDiscoveryError('PLEX_STORAGE_READ_FAILED') from None
