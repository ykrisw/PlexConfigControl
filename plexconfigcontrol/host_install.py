"""Read-only preparation of the PlexConfigControl installation on TrueNAS.

The Apps installer owns the managed iXVolume and the deployment job.
"""
import argparse
import ipaddress
import json
import stat
import subprocess
from pathlib import Path

from .deployment import Deployment
from .installation_storage import plan_storage
from .plex_storage import _zfs


APP = 'plexconfigcontrol'
APPS_MOUNT = '/mnt/.ix-apps'
UID = 568
_READ_METHODS = {'system.version', 'docker.config', 'app.query', 'app.config',
                 'app.ix_volume.query', 'filesystem.statfs'}


class InstallError(RuntimeError):
    pass


class LocalMiddleware:
    """Fixed middleware verbs and argument lists, never shell evaluation."""
    def __init__(self, runner=subprocess.run):
        self.runner = runner

    def call(self, method, *params):
        if method not in _READ_METHODS:
            raise InstallError('Unsupported installer lookup')
        command = ['midclt', 'call', method, *(json.dumps(value) for value in params)]
        try:
            result = self.runner(command, check=True, capture_output=True, text=True,
                                 timeout=30)
            return json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            raise InstallError(f'TrueNAS did not confirm {method}') from None


def _verify_private_file(path, *, owner=None):
    path = Path(path)
    if path.resolve(strict=True) != path:
        raise InstallError('Installation files must use real paths')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or (owner is not None and
            (info.st_uid != owner or info.st_mode & 0o077 or not info.st_mode & stat.S_IRUSR)):
        raise InstallError('Invalid ownership or permissions on an installation file')


def _verify_local_images(deployment):
    try:
        subprocess.run(['docker', 'image', 'inspect', deployment.panel_image, deployment.worker_image],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        raise InstallError('The panel and worker images must be built locally before installation') from None


def form_settings(values, *, panel_image, worker_image, sqlite_version):
    """Translate native form values; package metadata supplies the image and SQLite versions."""
    panel, backup, connection, plex = (values[key] for key in ('panel', 'backup', 'connection', 'plex'))
    mode = plex.get('storage_mode', 'automatic')
    if mode not in ('automatic', 'manual') or (mode == 'manual' and not plex.get('manual_source')):
        raise InstallError('Choose automatic Plex detection or a valid manual path')
    address = ipaddress.ip_address(panel['host_ip'])
    api_host = f'[{address}]' if address.version == 6 else str(address)
    return {
        'panel_image': panel_image, 'worker_image': worker_image, 'sqlite_version': sqlite_version,
        'host_ip': panel['host_ip'], 'host_port': panel['host_port'], 'verifier_file': panel['verifier_file'],
        'archive_parent': backup['archive_parent'], 'folder_name': backup['folder_name'],
        'archive_prefix': backup['archive_prefix'],
        'api_url': connection.get('api_url') or f'wss://{api_host}/api/current',
        'api_user': connection['api_user'],
        'api_key_file': connection['api_key_file'], 'api_ca_file': connection['api_ca_file'],
        'manual_source': plex.get('manual_source') if mode == 'manual' else None,
    }


def prepare(api, settings):
    """Read-only installation plan. All source paths come from trusted inputs or middleware."""
    if api.call('system.version') != 'TrueNAS-25.10.8':
        raise InstallError('This installer targets TrueNAS 25.10.8')
    if api.call('app.query', [['name', '=', APP]], {'select': ['name']}) != []:
        raise InstallError('PlexConfigControl already exists or its name cannot be checked')
    apps_dataset, apps_mount = _zfs(api, APPS_MOUNT)
    docker = api.call('docker.config')
    if apps_mount != APPS_MOUNT or not isinstance(docker, dict) or docker.get('dataset') != apps_dataset:
        raise InstallError('The managed Apps dataset cannot be confirmed')
    state = APPS_MOUNT + '/app_mounts/' + APP + '/state'
    if api.call('app.ix_volume.query', [['app_name', '=', APP]]) != []:
        raise InstallError('A state volume already exists for PlexConfigControl or cannot be checked')
    data = dict(settings)
    storage = plan_storage(api, data.pop('archive_parent'), manual_source=data.pop('manual_source', None),
                           folder_name=data.pop('folder_name', None), archive_prefix=data.pop('archive_prefix', None))
    deployment = Deployment(**data, state=state,
                            archives=str(Path(storage.parent)/storage.naming.folder_name),
                            plex_config=storage.plex.source, plex_dataset=storage.plex.dataset)
    _verify_private_file(deployment.api_key_file, owner=UID)
    _verify_private_file(deployment.verifier_file, owner=UID)
    _verify_private_file(deployment.api_ca_file)
    _verify_local_images(deployment)
    return deployment


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verify the PlexConfigControl installation form')
    parser.add_argument('configuration', type=Path)
    parser.add_argument('--panel-image', required=True)
    parser.add_argument('--worker-image', required=True)
    parser.add_argument('--sqlite-version', required=True)
    args = parser.parse_args(argv)
    try:
        with args.configuration.open(encoding='utf-8') as stream:
            values = json.load(stream)
        settings = form_settings(values, panel_image=args.panel_image,
                                 worker_image=args.worker_image, sqlite_version=args.sqlite_version)
        deployment = prepare(LocalMiddleware(), settings)
        print(json.dumps({'app': APP, 'state': deployment.state,
                          'archives': deployment.archives, 'plex_dataset': deployment.plex_dataset,
                          'host_ip': deployment.host_ip, 'host_port': deployment.host_port}, indent=2))
        return 0
    except InstallError as error:
        print(str(error))
    except Exception:
        print('PlexConfigControl could not verify the installation configuration.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
