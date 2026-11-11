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
        elif (method != 'GET' or not isinstance(fields, dict)
              or fields.get('func') != 'extra_get'
              or set(fields) != {'func', 'volumeID', 'snapshot_list', 'snap_start', 'snap_count', 'sid'}):
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

    def snapshots(self, volume_id):
        """Read one bounded inventory page; never mistake truncation for absence."""
        if type(volume_id) is not int or not 1 <= volume_id <= 9999999999:
            raise ValueError('Invalid QNAP volume ID')
        if self._session is None:
            raise QnapApiError('QNAP_LOGIN_REQUIRED')
        root = self._xml('GET', '/cgi-bin/disk/snapshot.cgi', {
            'func': 'extra_get', 'volumeID': str(volume_id), 'snapshot_list': '1',
            'snap_start': '0', 'snap_count': '100', 'sid': self._session,
        })
        if root.findtext('authPassed') == '0':
            self._session = None
            raise QnapApiError('QNAP_SESSION_EXPIRED')
        result = root.findtext('result', '')
        listing = root.find('SnapshotList')
        if not re.fullmatch(r'[0-9]+', result) or listing is None:
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
