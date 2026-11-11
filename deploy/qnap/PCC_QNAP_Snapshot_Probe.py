#!/usr/bin/env python3
# PlexConfigControl — developer snapshot diagnostic. MIT license.


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


"""Experimental, read-only QNAP management session over fixed loopback HTTPS.

No storage mutations are implemented here. CGI compatibility on QuTS hero is
not established by the fixture tests. Passwords are sent only in POST bodies.
The snapshot CGI uses a session parameter in its GET query over verified local
HTTPS. Request targets and session values must never be logged or returned in
diagnostic exceptions. This client does not persist credentials or sessions.
"""
import base64
import hashlib
import hmac
import http.client
import re
import ssl
from urllib.parse import urlencode
from xml.etree import ElementTree


class QnapApiError(RuntimeError):
    pass


def local_certificate_context(trusted_pem):
    """Build trust from an administrator-controlled local NAS certificate.

    Caller must read this from trusted local configuration, never from the
    network or a browser upload. Only public certificate blocks are loaded;
    a co-located server private key is neither used nor returned. The exact
    leaf pin replaces DNS-name matching for the fixed 127.0.0.1 connection.
    Certificate-chain/signature/expiry verification remains enabled.
    """
    certificates = re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',
                              trusted_pem, re.DOTALL)
    if not certificates:
        raise ValueError('Trusted local NAS certificate is required')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    context.load_verify_locations(cadata='\n'.join(certificates))
    fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificates[0])).hexdigest()
    return context, fingerprint


class QnapLocalReadOnlyApi:
    def __init__(self, port, *, tls_context=None, certificate_sha256=None,
                 connection_factory=http.client.HTTPSConnection):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid QNAP local management port')
        context = tls_context if tls_context is not None else ssl.create_default_context()
        context.minimum_version = max(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        if (context.verify_mode != ssl.CERT_REQUIRED
                or (not context.check_hostname and certificate_sha256 is None)
                or (certificate_sha256 is not None
                    and not re.fullmatch(r'[0-9a-f]{64}', certificate_sha256))):
            raise ValueError('Verified QNAP HTTPS identity is required')
        self.port = port
        self._tls_context = context
        self._certificate_sha256 = certificate_sha256
        self._connection_factory = connection_factory
        self._session = None

    def _xml(self, method, path, fields=None):
        if path not in ('/cgi-bin/authLogin.cgi', '/cgi-bin/disk/snapshot.cgi'):
            raise QnapApiError('QNAP_ENDPOINT_NOT_ALLOWED')
        if path == '/cgi-bin/authLogin.cgi':
            if method not in ('GET', 'POST') or (method == 'GET' and fields is not None):
                raise QnapApiError('QNAP_ENDPOINT_NOT_ALLOWED')
        else:
            list_fields = {'func', 'volumeID', 'snapshot_list', 'start', 'end', 'sid'}
            count_fields = {'func', 'volumeID', 'snapshot_count', 'by_vol', 'sid'}
            if (method != 'GET' or not isinstance(fields, dict)
                    or fields.get('func') != 'extra_get'
                    or set(fields) not in (list_fields, count_fields)):
                raise QnapApiError('QNAP_ENDPOINT_NOT_ALLOWED')
        return self._exchange_xml(method, path, fields)

    def _exchange_xml(self, method, path, fields=None):
        """Private verified transport; operation policy belongs to its caller.

        Public read methods always go through _xml's read-only operation guard.
        The developer lifecycle probe supplies its own stricter ownership guard.
        This transport is not a web/RPC endpoint.
        """
        if method not in ('GET', 'POST') or path not in (
                '/cgi-bin/authLogin.cgi', '/cgi-bin/disk/snapshot.cgi'):
            raise QnapApiError('QNAP_ENDPOINT_NOT_ALLOWED')
        target = path
        body = None
        if fields is not None:
            encoded = urlencode(fields)
            if method == 'GET':
                target += '?'+encoded
            else:
                body = encoded.encode('ascii')
        connection = None
        try:
            connection = self._connection_factory('127.0.0.1', self.port, timeout=15,
                                                  context=self._tls_context)
            connection.set_debuglevel(0)
            connection.connect()
            if self._certificate_sha256 is not None:
                certificate = connection.sock.getpeercert(binary_form=True)
                if not certificate or not hmac.compare_digest(
                        hashlib.sha256(certificate).hexdigest(), self._certificate_sha256):
                    raise QnapApiError('QNAP_LOCAL_CERTIFICATE_MISMATCH')
            connection.request(method, target, body=body, headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/xml, text/xml',
            })
            response = connection.getresponse()
            if response.status != 200:
                # Never follow a redirect, especially with credentials/session.
                raise QnapApiError('QNAP_LOCAL_API_HTTP_ERROR')
            data = response.read(1024*1024+1)
        except (OSError, http.client.HTTPException):
            raise QnapApiError('QNAP_LOCAL_API_UNAVAILABLE') from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass
        if (len(data) > 1024*1024 or b'<!DOCTYPE' in data.upper()
                or b'<!ENTITY' in data.upper()):
            raise QnapApiError('QNAP_API_INVALID_XML')
        try:
            return ElementTree.fromstring(data)
        except ElementTree.ParseError:
            raise QnapApiError('QNAP_API_INVALID_XML') from None

    def probe(self):
        """Return only nonsensitive shape information; no login attempt."""
        root = self._xml('GET', '/cgi-bin/authLogin.cgi')
        return {'root': root.tag, 'authentication_field': root.find('authPassed') is not None}

    def login(self, username, password):
        self._session = None
        if (not isinstance(username, str) or not username or len(username) > 256
                or not isinstance(password, str) or not password or len(password) > 4096):
            raise QnapApiError('QNAP_CREDENTIALS_REQUIRED')
        root = self._xml('POST', '/cgi-bin/authLogin.cgi', {
            'user': username, 'pwd': base64.b64encode(password.encode('utf-8')).decode('ascii'),
            'serviceKey': '1',
        })
        sid = root.findtext('authSid', '')
        if root.findtext('authPassed') != '1' or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', sid):
            raise QnapApiError('QNAP_AUTHENTICATION_FAILED')
        self._session = sid

    def _read_inventory(self, volume_id, fields):
        if type(volume_id) is not int or not 1 <= volume_id <= 9999999999:
            raise ValueError('Invalid QNAP volume ID')
        if self._session is None:
            raise QnapApiError('QNAP_LOGIN_REQUIRED')
        root = self._xml('GET', '/cgi-bin/disk/snapshot.cgi', {
            'func': 'extra_get', 'volumeID': str(volume_id),
            **fields, 'sid': self._session,
        })
        if root.findtext('authPassed') == '0':
            self._session = None
            raise QnapApiError('QNAP_SESSION_EXPIRED')
        if root.findtext('authPassed') != '1' or root.findtext('result') != '0':
            raise QnapApiError('QNAP_SNAPSHOT_SCHEMA_UNVERIFIED')
        return root

    def snapshot_count(self, volume_id):
        """Read the native volume-scoped counter independently of list presence."""
        root = self._read_inventory(volume_id, {'snapshot_count': '1', 'by_vol': '1'})
        if root.findtext('volumeID') != str(volume_id):
            raise QnapApiError('QNAP_SNAPSHOT_VOLUME_MISMATCH')
        count = root.findtext('snapshot_count', '')
        if not re.fullmatch(r'[0-9]{1,6}', count):
            raise QnapApiError('QNAP_SNAPSHOT_SCHEMA_UNVERIFIED')
        return int(count)

    def snapshots(self, volume_id):
        """Read one bounded page; missing XML needs an independently verified zero.

        Native QuTS hero may omit SnapshotList for a zero/failed enumeration.
        The success code alone is not proof that no snapshots exist.
        """
        root = self._read_inventory(volume_id, {'snapshot_list': '1', 'start': '0', 'end': '99'})
        listing = root.find('SnapshotList')
        if listing is None:
            if self.snapshot_count(volume_id) == 0:
                return []
            raise QnapApiError('QNAP_SNAPSHOT_SCHEMA_UNVERIFIED')
        nodes = listing.findall('row')
        if len(nodes) >= 100:
            raise QnapApiError('QNAP_SNAPSHOT_PAGE_LIMIT')
        rows = []
        identifiers = set()
        for node in nodes:
            identifier = node.findtext('snapshot_id', '')
            name = node.findtext('snapshot_name', '')
            if (not re.fullmatch(r'[1-9][0-9]{0,19}', identifier)
                    or identifier in identifiers or not name or len(name) > 256
                    or any(ord(char) < 32 for char in name)):
                raise QnapApiError('QNAP_SNAPSHOT_SCHEMA_UNVERIFIED')
            declared_volume = node.findtext('volume_id')
            if declared_volume is not None and declared_volume != str(volume_id):
                raise QnapApiError('QNAP_SNAPSHOT_VOLUME_MISMATCH')
            identifiers.add(identifier)
            rows.append({'id': identifier, 'name': name})
        return rows

    def forget_session(self):
        """Drop this client's session reference; server expiry remains server-owned."""
        self._session = None


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


def snapshot_mount_source(path, mountinfo, dataset):
    """Identify the deepest covering ZFS snapshot mount, never a live mount."""
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
    source = decode(filesystem[1])
    if (filesystem[0] != 'zfs' or 'ro' not in fields[5].split(',')
            or not source.startswith(dataset+'@') or not source[len(dataset)+1:]):
        raise SnapshotProbeError('PROBE_MOUNT_NOT_SCOPED_READONLY_SNAPSHOT')
    return source


def inspect_snapshot_data(installation, snapshot_id, baseline, runner=subprocess.run):
    """Mount the owned snapshot and inspect only file metadata through held fds."""
    result = runner(['/sbin/snapshot_util', 'mount_snapshot', snapshot_id],
                    capture_output=True, text=True, timeout=30, check=False)
    preview = result.stdout.strip()
    if result.returncode != 0 or not preview.startswith(('/share/', '/mnt/snapshot/')) or '\n' in preview:
        raise SnapshotProbeError('PROBE_SNAPSHOT_MOUNT_FAILED')
    root = Path(preview).resolve(strict=True)
    source = snapshot_mount_source(str(root), Path('/proc/self/mountinfo').read_text(), installation.dataset)
    if source in baseline:
        raise SnapshotProbeError('PROBE_MOUNT_POINTS_TO_PREEXISTING_SNAPSHOT')
    relative = PurePosixPath(installation.relative_path)
    if relative.is_absolute() or any(part in ('.', '..') for part in relative.parts) or not relative.parts:
        raise SnapshotProbeError('PROBE_INVALID_PLEX_SUBTREE')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    handles = []
    try:
        fd = os.open(root, flags)
        handles.append(fd)
        if not os.statvfs(fd).f_flag & os.ST_RDONLY:
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
        self.inspect_data = inspect_data or (lambda identifier, baseline: inspect_snapshot_data(installation, identifier, baseline))
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

    def _wait(self, condition):
        deadline = self.clock()+60
        for _ in range(30):
            value = condition()
            if value:
                return value
            if self.clock() >= deadline:
                break
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
        if root.findtext('authPassed') != '1' or root.findtext('result') != '0':
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
        self._wait(absent)
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


"""Explicit opt-in, developer-only snapshot lifecycle diagnostic."""


def snapshot_probe_main():
    import getpass
    import os
    import sys
    from pathlib import Path

    if sys.argv[1:] != ['--test-snapshot']:
        print('Test jednej tymczasowej migawki QNAP. Uruchom z --test-snapshot.')
        return 2
    print('PlexConfigControl — test migawki QNAP', flush=True)
    print('Utworzy jedną migawkę wolumenu Plexa, sprawdzi odczyt danych i usunie tę migawkę.')
    print('Nie zatrzymuje Plexa i nie przywraca danych. Nie usuwa istniejących migawek.', flush=True)
    api = None
    try:
        installation = discover_qnap_plex()
        print('Identyfikator wolumenu Plexa:', installation.volume_id)
        context, pin = local_certificate_context(Path('/etc/stunnel/stunnel.pem').read_text())
        api = QnapLocalReadOnlyApi(443, tls_context=context, certificate_sha256=pin)
        if api.probe()['root'] != 'QDocRoot':
            raise QnapApiError('QNAP_API_INVALID_XML')
        print('HTTPS i certyfikat: OK')
        default_user = os.environ.get('SUDO_USER') or getpass.getuser()
        username = input('Użytkownik QNAP ['+default_user+']: ').strip() or default_user
        password = getpass.getpass('Hasło konta QNAP: ')
        try:
            api.login(username, password)
        finally:
            del password
        print('Logowanie: OK', flush=True)
        labels = {
            'CREATING': 'Tworzenie migawki testowej',
            'CREATED': 'Utworzono migawkę — ID',
            'READ_ONLY_PLEX_DATA_CONFIRMED': 'Odczyt plików Plexa z migawki tylko do odczytu: OK — ID',
            'CLEANUP_CONFIRMED': 'Usunięcie migawki potwierdzone przez API i ZFS — ID',
        }
        probe = OwnedSnapshotProbe(api, installation,
            report=lambda stage, value: print(labels[stage]+': '+str(value), flush=True))
        result = probe.run()
        if result['error']:
            print('Błąd testu:', result['error'], flush=True)
        if result['cleanup_error']:
            print('NIE POTWIERDZONO USUNIĘCIA:', result['cleanup_error'])
            print('Nazwa migawki:', result['name'])
            print('ID migawki:', result['id'] or 'nieustalone')
            print('Zażądano wygaśnięcia po 15 minutach; nie zastępuje to potwierdzenia usunięcia.')
        if result['created'] and result['readable'] and result['cleanup_confirmed'] and not result['error']:
            print('Wynik całego testu: OK', flush=True)
            return 0
        return 1
    except (QnapApiError, QnapDiscoveryError, SnapshotProbeError) as error:
        print('Wynik testu:', str(error), flush=True)
        return 1
    except (Exception, KeyboardInterrupt) as error:
        print('Wynik testu:', type(error).__name__, flush=True)
        return 1
    finally:
        if api is not None:
            api.forget_session()


if __name__ == '__main__':
    raise SystemExit(snapshot_probe_main())
