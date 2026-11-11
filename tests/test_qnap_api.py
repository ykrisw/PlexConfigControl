import http.client
import hashlib
import ssl
import tempfile
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit

from plexconfigcontrol.qnap_api import QnapApiError, QnapLocalReadOnlyApi, local_certificate_context


LOGIN = b'<QDocRoot><authPassed>1</authPassed><authSid>test-session-only</authSid></QDocRoot>'
EMPTY = b'<QDocRoot><authPassed>1</authPassed><result>0</result><SnapshotList/></QDocRoot>'


class QnapApiTests(unittest.TestCase):
    def client(self, replies, **tls_options):
        self.calls = []
        self.closed = []
        calls, closed = self.calls, self.closed
        class Connection:
            def __init__(self, host, port, **options):
                self.reply = replies.pop(0)
                self.status = self.reply[0]
                calls.append(('connect', host, port, options))
                self.sock = self
            def connect(self):
                calls.append(('tls-connected',))
            def getpeercert(self, **options):
                return b'test-certificate'
            def set_debuglevel(self, level):
                calls.append(('debug', level))
            def request(self, method, path, **options):
                calls.append(('request', method, path, options))
            def getresponse(self):
                return self
            def read(self, limit):
                return self.reply[1][:limit]
            def close(self):
                closed.append(True)
        return QnapLocalReadOnlyApi(443, connection_factory=Connection, **tls_options)

    def test_password_is_post_only_and_snapshot_query_uses_native_get_over_loopback(self):
        client = self.client([(200, LOGIN), (200, EMPTY)])
        client.login('test-account', 'test-password')
        self.assertEqual(client.snapshots(7), [])
        requests = [call for call in self.calls if call[0] == 'request']
        self.assertEqual(requests[0][1:3], ('POST', '/cgi-bin/authLogin.cgi'))
        self.assertEqual(parse_qs(requests[0][3]['body'].decode())['user'], ['test-account'])
        self.assertEqual(requests[1][1], 'GET')
        target = urlsplit(requests[1][2])
        self.assertEqual(target.path, '/cgi-bin/disk/snapshot.cgi')
        self.assertEqual(parse_qs(target.query)['sid'], ['test-session-only'])
        self.assertEqual(parse_qs(target.query)['volumeID'], ['7'])
        self.assertEqual(parse_qs(target.query)['start'], ['0'])
        self.assertEqual(parse_qs(target.query)['end'], ['99'])
        self.assertNotIn('snap_start', parse_qs(target.query))
        self.assertNotIn('pwd', parse_qs(target.query))
        self.assertIsNone(requests[1][3]['body'])
        self.assertTrue(all(call[1] == '127.0.0.1' for call in self.calls if call[0] == 'connect'))
        self.assertEqual(len(self.closed), 2)

    def test_probe_never_sends_credentials_or_returns_session_fields(self):
        client = self.client([(200, LOGIN)])
        self.assertEqual(client.probe(), {'root':'QDocRoot', 'authentication_field':True})
        self.assertIsNone([call for call in self.calls if call[0] == 'request'][0][3]['body'])

    def test_redirect_is_rejected_without_retry(self):
        client = self.client([(302, b'private response')])
        with self.assertRaisesRegex(QnapApiError, '^QNAP_LOCAL_API_HTTP_ERROR$'):
            client.login('test-account', 'test-password')
        self.assertEqual(len(self.closed), 1)

    def test_invalid_or_dangerous_xml_is_rejected(self):
        for data in (b'invalid', b'<!DOCTYPE x><x/>', b'<!ENTITY x "x"><x/>', b'x'*1048577):
            client = self.client([(200, data)])
            with self.subTest(data=data[:20]), self.assertRaisesRegex(QnapApiError, '^QNAP_API_INVALID_XML$'):
                client.probe()

    def test_auth_failure_and_transport_errors_never_include_credentials(self):
        client = self.client([(200, b'<x><authPassed>0</authPassed></x>')])
        with self.assertRaisesRegex(QnapApiError, '^QNAP_AUTHENTICATION_FAILED$'):
            client.login('private-account', 'private-password')
        def unavailable(*args, **options):
            raise OSError('private transport details')
        with self.assertRaisesRegex(QnapApiError, '^QNAP_LOCAL_API_UNAVAILABLE$'):
            QnapLocalReadOnlyApi(8080, connection_factory=unavailable).probe()

    def test_missing_or_expired_session_blocks_inventory(self):
        client = self.client([(200, LOGIN), (200, b'<x><authPassed>0</authPassed></x>')])
        with self.assertRaisesRegex(QnapApiError, 'LOGIN_REQUIRED'):
            client.snapshots(7)
        client.login('test-account', 'test-password')
        with self.assertRaisesRegex(QnapApiError, 'SESSION_EXPIRED'):
            client.snapshots(7)
        with self.assertRaisesRegex(QnapApiError, 'LOGIN_REQUIRED'):
            client.snapshots(7)

    def test_unknown_schema_cannot_be_treated_as_no_snapshots(self):
        client = self.client([(200, LOGIN), (200, b'<x><result>0</result></x>')])
        client.login('test-account', 'test-password')
        with self.assertRaisesRegex(QnapApiError, 'SCHEMA_UNVERIFIED'):
            client.snapshots(7)

    def test_foreign_volume_and_duplicate_rows_are_rejected(self):
        row = b'<row><snapshot_id>9001</snapshot_id><snapshot_name>test-snapshot</snapshot_name><volume_id>8</volume_id></row>'
        for rows in (row, row.replace(b'>8<', b'>7<')*2):
            data = b'<x><authPassed>1</authPassed><result>0</result><SnapshotList>'+rows+b'</SnapshotList></x>'
            client = self.client([(200, LOGIN), (200, data)])
            client.login('test-account', 'test-password')
            with self.assertRaises(QnapApiError):
                client.snapshots(7)

    def test_full_page_is_not_assumed_complete(self):
        row = b'<row><snapshot_id>9001</snapshot_id><snapshot_name>test</snapshot_name></row>'
        client = self.client([(200, LOGIN), (200, b'<x><authPassed>1</authPassed><result>0</result><SnapshotList>'+row*100+b'</SnapshotList></x>')])
        client.login('test-account', 'test-password')
        with self.assertRaisesRegex(QnapApiError, 'PAGE_LIMIT'):
            client.snapshots(7)

    def test_invalid_ports_and_volume_ids_are_rejected(self):
        for port in (True, 0, 65536, '8080'):
            with self.assertRaises(ValueError):
                QnapLocalReadOnlyApi(port)
        client = self.client([])
        for volume in (True, 0, -1, '7'):
            with self.assertRaises(ValueError):
                client.snapshots(volume)

    def test_unverified_tls_or_hostname_without_pin_is_rejected(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        with self.assertRaises(ValueError):
            self.client([], tls_context=context)
        context.verify_mode = ssl.CERT_NONE
        with self.assertRaises(ValueError):
            self.client([], tls_context=context, certificate_sha256='a'*64)

    def test_certificate_mismatch_blocks_credentials_before_http_request(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        client = self.client([(200, LOGIN)], tls_context=context, certificate_sha256='a'*64)
        with self.assertRaisesRegex(QnapApiError, '^QNAP_LOCAL_CERTIFICATE_MISMATCH$'):
            client.login('test-account', 'test-password')
        self.assertFalse(any(call[0] == 'request' for call in self.calls))
        self.assertEqual(len(self.closed), 1)

    def test_exact_local_certificate_pin_allows_request(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        client = self.client([(200, LOGIN)], tls_context=context,
            certificate_sha256=hashlib.sha256(b'test-certificate').hexdigest())
        client.login('test-account', 'test-password')
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_local_trust_loader_uses_public_certificate_from_combined_bundle(self):
        from plexconfigcontrol.tls import ensure_tls
        with tempfile.TemporaryDirectory() as directory:
            cert, key = ensure_tls(Path(directory), 'localhost')
            pem = cert.read_text()
            context, fingerprint = local_certificate_context(key.read_text()+pem)
            self.assertEqual(fingerprint, hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest())
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertFalse(context.check_hostname)
            self.assertGreaterEqual(context.cert_store_stats()['x509'], 1)
            with self.assertRaises(ValueError):
                local_certificate_context(key.read_text())

    def test_read_only_transport_rejects_mutations_and_get_login_fields(self):
        client = self.client([])
        for method, path, fields in (
                ('GET', '/cgi-bin/authLogin.cgi', {'user':'test', 'pwd':'test'}),
                ('POST', '/cgi-bin/disk/snapshot.cgi', {'func':'extra_get'}),
                ('GET', '/cgi-bin/disk/snapshot.cgi', {'func':'del_snapshots', 'snapshotID':'9001'})):
            with self.subTest(method=method, path=path), self.assertRaisesRegex(QnapApiError, '^QNAP_ENDPOINT_NOT_ALLOWED$'):
                client._xml(method, path, fields)
        self.assertEqual(self.calls, [])

    def test_native_counter_uses_by_vol_and_checks_echoed_volume(self):
        data = b'<QDocRoot><authPassed>1</authPassed><result>0</result><volumeID>7</volumeID><snapshot_count>3</snapshot_count></QDocRoot>'
        client = self.client([(200, LOGIN), (200, data)])
        client.login('test-account', 'test-password')
        self.assertEqual(client.snapshot_count(7), 3)
        query = parse_qs(urlsplit([c for c in self.calls if c[0] == 'request'][-1][2]).query)
        self.assertEqual(query['by_vol'], ['1'])
        self.assertEqual(query['snapshot_count'], ['1'])
        client = self.client([(200, LOGIN), (200, data)])
        client.login('test-account', 'test-password')
        with self.assertRaisesRegex(QnapApiError, 'VOLUME_MISMATCH'):
            client.snapshot_count(8)

    def test_missing_list_is_empty_only_with_separately_verified_zero_count(self):
        missing = b'<QDocRoot><authPassed>1</authPassed><result>0</result></QDocRoot>'
        for count in (b'0', b'1', b'-1', b'invalid'):
            counter = b'<QDocRoot><authPassed>1</authPassed><result>0</result><volumeID>7</volumeID><snapshot_count>'+count+b'</snapshot_count></QDocRoot>'
            client = self.client([(200, LOGIN), (200, missing), (200, counter)])
            client.login('test-account', 'test-password')
            with self.subTest(count=count):
                if count == b'0':
                    self.assertEqual(client.snapshots(7), [])
                else:
                    with self.assertRaises(QnapApiError):
                        client.snapshots(7)
