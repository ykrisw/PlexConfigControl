"""Render the single TrueNAS Apps definition from trusted installer inputs.

This module neither provisions a volume nor deploys the app. The state path
must be supplied by the installer after provisioning its managed iXVolume.
"""
import ipaddress
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from .snapshots import Snapshots

_STATE = '/var/lib/plexconfigcontrol'
_ARCHIVES = '/var/lib/plex-archives'
_CONFIG = '/var/lib/plex-config'
_SOCKET = _STATE + '/execution.sock'
_SECRETS = '/run/pcc-secrets'


def _path(value):
    if not isinstance(value, str) or not value.startswith('/mnt/') or any(ord(c) < 32 or c in '$\\' for c in value):
        raise ValueError('Select an absolute path on a TrueNAS dataset')
    path = PurePosixPath(value)
    if str(path) != value or '..' in path.parts or path == PurePosixPath('/mnt'):
        raise ValueError('Select a normalized path on a TrueNAS dataset')
    return path


def _bind(source, target, *, readonly=False, propagation=None):
    mount = {'type': 'bind', 'source': source, 'target': target, 'read_only': readonly,
             'bind': {'create_host_path': False}}
    if propagation is not None:
        mount['bind']['propagation'] = propagation
    return mount


@dataclass(frozen=True)
class Deployment:
    panel_image: str
    worker_image: str
    state: str
    archives: str
    plex_config: str
    plex_dataset: str
    api_url: str
    api_user: str
    api_key_file: str
    api_ca_file: str
    verifier_file: str
    host_ip: str
    host_port: int
    sqlite_version: str

    def __post_init__(self):
        paths = [self.state, self.archives, self.plex_config,
                 self.api_key_file, self.api_ca_file, self.verifier_file]
        paths = [_path(path) for path in paths]
        protected = PurePosixPath('/mnt/TrueNAS/TrueNAS/PBS-Data')
        for index, first in enumerate(paths):
            for second in [protected, *paths[index + 1:]]:
                if first == second or first in second.parents or second in first.parents:
                    raise ValueError('Application mounts overlap or use protected storage')
        Snapshots(None, None, self.plex_dataset)
        url = urlsplit(self.api_url)
        if (url.scheme != 'wss' or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path != '/api/current'):
            raise ValueError('The TrueNAS endpoint must use verified WSS')
        _ = url.port  # Validate optional explicit TLS port.
        ip = ipaddress.ip_address(self.host_ip)
        if ip.is_unspecified or ip.is_multicast or not 1024 <= self.host_port <= 65535:
            raise ValueError('Select the TrueNAS IP and an unprivileged port')
        if (not re.fullmatch(r'\d+\.\d+\.\d+', self.sqlite_version)
                or not self.api_user
                or any(ord(c) < 32 or c == '$' for c in self.api_user + self.api_url + self.plex_dataset)):
            raise ValueError('Invalid execution configuration')
        for image in (self.panel_image, self.worker_image):
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@-]+', image):
                raise ValueError('A fixed application image is required')

    def compose(self):
        panel = {
            'image': self.panel_image,
            'pull_policy': 'never',
            'user': '568:568',
            'restart': 'unless-stopped',
            'read_only': True,
            'cap_drop': ['ALL'],
            'security_opt': ['no-new-privileges:true'],
            'tmpfs': ['/tmp'],
            'ports': [{'target': 8443, 'published': str(self.host_port), 'host_ip': self.host_ip,
                       'protocol': 'tcp'}],
            'environment': {
                'PCC_PUBLIC_HOST': self.host_ip,
                'PCC_ARCHIVE_DIRECTORY': _ARCHIVES,
                'PCC_EXECUTION_SOCKET': _SOCKET,
                'PCC_EXECUTION_UID': '568',
                'PCC_BOOTSTRAP_VERIFIER_FILE': _SECRETS + '/panel-verifier',
            },
            'volumes': [_bind(self.state, _STATE), _bind(self.archives, _ARCHIVES, readonly=True),
                        _bind(self.verifier_file, _SECRETS + '/panel-verifier', readonly=True)],
        }
        worker = {
            'image': self.worker_image,
            'pull_policy': 'never',
            'user': '0:0',
            'restart': 'unless-stopped',
            'read_only': True,
            'cap_drop': ['ALL'],
            # SETUID, SETGID and SETPCAP are dropped by the entrypoint before Python.
            'cap_add': ['SETUID', 'SETGID', 'SETPCAP', 'CHOWN', 'DAC_OVERRIDE', 'FOWNER', 'FSETID'],
            'security_opt': ['no-new-privileges:true'],
            'tmpfs': ['/tmp'],
            'stop_grace_period': '2m',
            'command': [
                '--state', _STATE, '--archives', _ARCHIVES, '--config-mount', _CONFIG,
                '--host-config', self.plex_config, '--dataset', self.plex_dataset,
                '--socket', _SOCKET, '--panel-uid', '568', '--truenas-url', self.api_url,
                '--api-username', self.api_user, '--api-key-file', _SECRETS + '/truenas-key',
                '--ca-file', _SECRETS + '/truenas-ca', '--plex-sqlite', '/usr/local/bin/pcc-plex-sqlite',
                '--sqlite-version', self.sqlite_version,
            ],
            'volumes': [_bind(self.state, _STATE), _bind(self.archives, _ARCHIVES),
                        _bind(self.plex_config, _CONFIG, propagation='rslave'),
                        _bind(self.api_key_file, _SECRETS + '/truenas-key', readonly=True),
                        _bind(self.api_ca_file, _SECRETS + '/truenas-ca', readonly=True)],
        }
        return {'services': {'panel': panel, 'worker': worker}}


def main(argv=None):
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description='Render the PlexConfigControl TrueNAS Apps definition')
    parser.add_argument('configuration', type=Path)
    args = parser.parse_args(argv)
    try:
        with args.configuration.open(encoding='utf-8') as stream:
            data = json.load(stream)
        configuration = Deployment(**data)
    except (OSError, TypeError, ValueError):
        parser.exit(1, 'The deployment configuration is invalid. Check the paths, images and endpoint.\n')
    print(json.dumps(configuration.compose(), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
