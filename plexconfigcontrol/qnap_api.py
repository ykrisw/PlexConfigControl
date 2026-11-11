"""Experimental, read-only QNAP management session over fixed loopback HTTP.

No storage mutations are implemented here. CGI compatibility on QuTS hero is
not established by the fixture tests. Credentials and sessions stay in memory
and in POST bodies, never URLs, process arguments or diagnostic output.
"""
import base64
import http.client
import re
from urllib.parse import urlencode
from xml.etree import ElementTree


class QnapApiError(RuntimeError):
    pass


class QnapLocalReadOnlyApi:
    def __init__(self, port, *, connection_factory=http.client.HTTPConnection):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid QNAP local management port')
        self.port = port
        self._connection_factory = connection_factory
        self._session = None

    def _xml(self, method, path, fields=None):
        if path not in ('/cgi-bin/authLogin.cgi', '/cgi-bin/disk/snapshot.cgi'):
            raise QnapApiError('QNAP_ENDPOINT_NOT_ALLOWED')
        body = urlencode(fields).encode('ascii') if fields is not None else None
        connection = None
        try:
            connection = self._connection_factory('127.0.0.1', self.port, timeout=15)
            connection.set_debuglevel(0)
            connection.request(method, path, body=body, headers={
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
        root = self._xml('POST', '/cgi-bin/disk/snapshot.cgi', {
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
