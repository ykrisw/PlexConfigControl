"""Prepare verified storage and a Compose definition for TrueNAS Apps.

The Apps installer owns the managed iXVolume and the deployment job.
"""
import argparse
import ipaddress
import json
import os
import ssl
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .catalog_bundle import APP, catalog_files
from .deployment import Deployment
from .installation_storage import create_storage, plan_storage
from .naming import save_naming
from .storage import verify_destination
from .plex_storage import _zfs


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
        return self._call(method, params)

    def _call(self, method, params, *, job=False):
        command = ['midclt', 'call', *(['-job'] if job else []), method,
                   *(json.dumps(value) for value in params)]
        try:
            result = self.runner(command, check=True, capture_output=True, text=True,
                                 timeout=300 if job else 30)
            version = result.stdout.strip()
            if method == 'system.version' and version.startswith('TrueNAS-'):
                return version
            return json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            raise InstallError(f'TrueNAS did not confirm {method}') from None

    def allocate_state(self, deployment):
        name = deployment.panel_image.rsplit('/', 1)[-1]
        if ':' not in name or '@' in deployment.panel_image:
            raise InstallError('The locally built panel image requires an explicit tag')
        repository, tag = deployment.panel_image.rsplit(':', 1)
        return self._call('app.create', ({
            'app_name': APP, 'catalog_app': 'ix-app', 'train': 'stable', 'version': '1.4.8',
            'values': {
                'image': {'repository': repository, 'tag': tag, 'pull_policy': 'never'},
                'entrypoint': ['/bin/sleep'], 'command': ['infinity'],
                'disable_builtin_healthcheck': True, 'restart_policy': 'no',
                'run_as_custom_user': True, 'run_as': {'user': UID, 'group': UID},
                'storage': [{'type': 'ix_volume', 'read_only': False,
                             'mount_path': '/var/lib/plexconfigcontrol',
                             'ix_volume_config': {'dataset_name': 'state', 'acl_enable': False}}],
            },
        },), job=True)

    def convert(self):
        return self._call('app.convert_to_custom', (APP,), job=True)

    def configure(self, compose):
        return self._call('app.update', (APP, {'custom_compose_config': compose}), job=True)

    def start(self):
        return self._call('app.start', (APP,), job=True)


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


def _prepare(api, settings, *, provisioned=False):
    if api.call('system.version') != 'TrueNAS-25.10.8':
        raise InstallError('This installer targets TrueNAS 25.10.8')
    if not provisioned and api.call('app.query', [['name', '=', APP]], {'select': ['name']}) != []:
        raise InstallError('PlexConfigControl already exists or its name cannot be checked')
    apps_dataset, apps_mount = _zfs(api, APPS_MOUNT)
    docker = api.call('docker.config')
    if apps_mount != APPS_MOUNT or not isinstance(docker, dict) or docker.get('dataset') != apps_dataset:
        raise InstallError('The managed Apps dataset cannot be confirmed')
    state = APPS_MOUNT + '/app_mounts/' + APP + '/state'
    volumes = api.call('app.ix_volume.query', [['app_name', '=', APP]])
    if provisioned:
        if volumes != [{'app_name': APP, 'name': 'state'}]:
            raise InstallError('TrueNAS must provision the dedicated PlexConfigControl state volume first')
        if _zfs(api, state) != (f'{apps_dataset}/app_mounts/{APP}/state', state):
            raise InstallError('The managed state volume does not match the expected dataset')
    elif volumes != []:
        raise InstallError('A state volume already exists for PlexConfigControl or cannot be checked')
    data = dict(settings)
    archive_parent = data.pop('archive_parent')
    archive_dataset, archive_mount = _zfs(api, archive_parent)
    if archive_dataset == apps_dataset or archive_dataset.startswith(apps_dataset + '/'):
        raise InstallError('Choose archive storage outside the managed Apps dataset')
    storage = plan_storage(api, archive_parent, manual_source=data.pop('manual_source', None),
                           folder_name=data.pop('folder_name', None), archive_prefix=data.pop('archive_prefix', None))
    deployment = Deployment(**data, state=state,
                            archives=str(Path(storage.parent)/storage.naming.folder_name),
                            plex_config=storage.plex.source, plex_dataset=storage.plex.dataset)
    if archive_dataset == deployment.plex_dataset or archive_dataset.startswith(deployment.plex_dataset + '/'):
        raise InstallError('Archive storage must be separate from the Plex configuration dataset')
    _verify_private_file(deployment.api_key_file, owner=UID)
    _verify_private_file(deployment.verifier_file, owner=UID)
    _verify_private_file(deployment.api_ca_file)
    _verify_local_images(deployment)
    return deployment, storage, (archive_dataset, archive_mount)


def prepare(api, settings, *, provisioned=False):
    """Read-only review. The provisioned form is used after Apps allocates the iXVolume."""
    return _prepare(api, settings, provisioned=provisioned)[0]


def prepare_compose(api, settings, expected, *, confirmed=False):
    """Create the selected output once and render Compose after verifying both mounts."""
    if confirmed is not True or os.geteuid() != 0:
        raise InstallError('Explicit administrator confirmation is required')
    current = _prepare(api, settings, provisioned=True)
    if current != expected:
        raise InstallError('Installation settings changed after review')
    deployment, plan, archive_filesystem = current
    path = Path(deployment.state)
    if path.resolve(strict=True) != path:
        raise InstallError('The managed state path must not contain symlinks')
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.listdir(fd):
            raise InstallError('The managed state volume is already in use')
        # Exclusive creation consumes the empty-volume prerequisite before any
        # output writes. A crash leaves a record for administrative review.
        marker = os.open('install-preparation', os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW, 0o600, dir_fd=fd)
        os.close(marker)
        os.fsync(fd)
        destination = create_storage(api, plan)
        if (str(destination.root) != deployment.archives or not verify_destination(destination)
                or _zfs(api, deployment.archives) != archive_filesystem):
            raise InstallError('The selected archive destination could not be verified')
        save_naming(path, plan.naming)
        os.chown('output-naming.json', UID, UID, dir_fd=fd, follow_symlinks=False)
        os.fchmod(fd, 0o700)
        os.fchown(fd, UID, UID)
        os.fsync(fd)
    finally:
        os.close(fd)
    return deployment.compose()


def prepare_catalog(api, settings, expected, values, template_root, version, output, *, confirmed=False):
    """Prepare a fresh archive directory and write the native Apps version files."""
    if confirmed is not True or os.geteuid() != 0:
        raise InstallError('Explicit administrator confirmation is required')
    current = _prepare(api, settings)
    if current != expected:
        raise InstallError('Installation settings changed after review')
    deployment, plan, archive_filesystem = current
    files = catalog_files(template_root, deployment, plan, values, version)
    output = Path(output).absolute()
    if output.parent.resolve(strict=True) != output.parent:
        raise InstallError('The catalog output must use a real parent directory')
    for path in map(Path, (deployment.state, deployment.archives, deployment.plex_config)):
        if output == path or output in path.parents or path in output.parents:
            raise InstallError('The catalog output overlaps application storage')
    output.mkdir(mode=0o700)  # Exclusive reservation. Never overwrite a prior export.
    destination = create_storage(api, plan)
    if (str(destination.root) != deployment.archives or not verify_destination(destination)
            or _zfs(api, deployment.archives) != archive_filesystem):
        raise InstallError('The selected archive destination could not be verified')
    for name, body in files.items():
        path = output/name
        path.parent.mkdir(exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            stream.write(body)
    return output


def _ready(deployment, *, timeout=90):
    host = ipaddress.ip_address(deployment.host_ip)
    authority = f'[{host}]' if host.version == 6 else str(host)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            ca = Path(deployment.state)/'tls'/'panel.crt'
            context = ssl.create_default_context(cafile=str(ca))
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                  urllib.request.HTTPSHandler(context=context))
            with opener.open(f'https://{authority}:{deployment.host_port}/healthz', timeout=5) as response:
                if json.loads(response.read(256)) == {'ready': True, 'mode': 'operational'}:
                    return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise InstallError('TrueNAS created the app, but the panel and worker did not report readiness')


def install_app(api, settings, expected, *, confirmed=False):
    """Install once under a fixed Apps name. Interrupted installs are never replayed."""
    if confirmed is not True or os.geteuid() != 0:
        raise InstallError('Explicit administrator confirmation is required')
    if _prepare(api, settings) != expected:
        raise InstallError('Installation settings changed after review')
    deployment = expected[0]
    bootstrap = api.allocate_state(deployment)
    if not isinstance(bootstrap, dict) or bootstrap.get('name') != APP or bootstrap.get('custom_app') is not False:
        raise InstallError('TrueNAS did not confirm the state allocation app')
    compose = prepare_compose(api, settings, expected, confirmed=True)
    converted = api.convert()
    if not isinstance(converted, dict) or converted.get('name') != APP or converted.get('custom_app') is not True:
        raise InstallError('TrueNAS did not confirm conversion of PlexConfigControl')
    installed = api.configure(compose)
    if not isinstance(installed, dict) or installed.get('name') != APP or installed.get('custom_app') is not True:
        raise InstallError('TrueNAS did not confirm the final PlexConfigControl configuration')
    if installed.get('state') == 'STOPPED':
        api.start()
    _ready(deployment)
    return {'app': APP, 'host_ip': deployment.host_ip, 'port': deployment.host_port}

def main(argv=None):
    parser = argparse.ArgumentParser(description='Verify the PlexConfigControl installation form')
    parser.add_argument('configuration', type=Path)
    parser.add_argument('--panel-image', required=True)
    parser.add_argument('--worker-image', required=True)
    parser.add_argument('--sqlite-version', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-compose', action='store_true',
                      help='Prepare the confirmed paths after Apps provisions the iXVolume')
    mode.add_argument('--install', action='store_true',
                      help='Install the reviewed configuration as one application in TrueNAS Apps')
    mode.add_argument('--prepare-catalog', type=Path, metavar='OUTPUT',
                      help='Prepare a native Apps version directory for the reviewed settings')
    parser.add_argument('--catalog-template', type=Path)
    parser.add_argument('--catalog-version', default='0.1.0')
    args = parser.parse_args(argv)
    try:
        with args.configuration.open(encoding='utf-8') as stream:
            values = json.load(stream)
        settings = form_settings(values, panel_image=args.panel_image,
                                 worker_image=args.worker_image, sqlite_version=args.sqlite_version)
        api = LocalMiddleware()
        prepared = _prepare(api, settings, provisioned=args.prepare_compose)
        deployment, storage, _ = prepared
        review = {'app': APP, 'state': deployment.state, 'archives': deployment.archives,
                  'logs': deployment.archives + '/Logs', 'archive_prefix': storage.naming.archive_prefix,
                  'plex_dataset': deployment.plex_dataset,
                  'host_ip': deployment.host_ip, 'host_port': deployment.host_port}
        if args.prepare_compose or args.prepare_catalog or args.install:
            if args.prepare_catalog and args.catalog_template is None:
                raise InstallError('The catalog template directory is required')
            print(json.dumps(review, indent=2), file=sys.stderr)
            print(f'Type {APP} to prepare these paths: ', file=sys.stderr, end='', flush=True)
            if input() != APP:
                return 1
            if args.install:
                print(json.dumps(install_app(api, settings, prepared, confirmed=True)))
            elif args.prepare_catalog:
                output = prepare_catalog(api, settings, prepared, values, args.catalog_template,
                                         args.catalog_version, args.prepare_catalog, confirmed=True)
                print(json.dumps({'catalog_version_directory': str(output)}))
            else:
                compose = prepare_compose(api, settings, prepared, confirmed=True)
                print(json.dumps(compose, indent=2))
        else:
            print(json.dumps(review, indent=2))
        return 0
    except InstallError as error:
        print(str(error), file=sys.stderr)
    except Exception:
        print('PlexConfigControl could not prepare the installation. Check the reviewed paths before retrying.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
