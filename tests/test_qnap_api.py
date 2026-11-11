import http.client
import unittest
from urllib.parse import parse_qs

from plexconfigcontrol.qnap_api import QnapApiError, QnapLocalReadOnlyApi


LOGIN = b'<QDocRoot><authPassed>1</authPassed><authSid>test-session-only</authSid></QDocRoot>'
EMPTY = b'<QDocRoot><authPassed>1</authPassed><result>0</result><SnapshotList/></QDocRoot>'


class QnapApiTests(unittest.TestCase):
    def client(self, replies):
        self.calls = []
        self.closed = []
        calls, closed = self.calls, self.closed
        class Connection:
            def __init__(self, host, port, **options):
                self.reply = replies.pop(0)
                self.status = self.reply[0]
                calls.append(('connect', host, port, options))
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
        return QnapLocalReadOnlyApi(8080, connection_factory=Connection)

    def test_credentials_and_session_use_post_bodies_and_only_loopback(self):
        client = self.client([(200, LOGIN), (200, EMPTY)])
        client.login('test-account', 'test-password')
        self.assertEqual(client.snapshots(7), [])
        requests = [call for call in self.calls if call[0] == 'request']
        self.assertEqual([call[1:3] for call in requests], [
            ('POST', '/cgi-bin/authLogin.cgi'), ('POST', '/cgi-bin/disk/snapshot.cgi')])
        self.assertEqual(parse_qs(requests[1][3]['body'].decode())['sid'], ['test-session-only'])
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
            data = b'<x><result>0</result><SnapshotList>'+rows+b'</SnapshotList></x>'
            client = self.client([(200, LOGIN), (200, data)])
            client.login('test-account', 'test-password')
            with self.assertRaises(QnapApiError):
                client.snapshots(7)

    def test_full_page_is_not_assumed_complete(self):
        row = b'<row><snapshot_id>9001</snapshot_id><snapshot_name>test</snapshot_name></row>'
        client = self.client([(200, LOGIN), (200, b'<x><result>0</result><SnapshotList>'+row*100+b'</SnapshotList></x>')])
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
