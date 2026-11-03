import unittest
from unittest.mock import Mock, call

from tests.android_transport import fixture_tunnel


class AndroidTransportTests(unittest.TestCase):
    def test_local_endpoint_and_exact_mapping_cleanup(self):
        adb = Mock()
        with fixture_tunnel(adb, '32768') as url:
            self.assertEqual(url, 'https://127.0.0.1:32768')
            adb.assert_called_once_with('reverse', '--no-rebind', 'tcp:32768', 'tcp:32768')
        self.assertEqual(adb.call_args_list[-1], call('reverse', '--remove', 'tcp:32768'))

    def test_navigation_failure_still_removes_mapping_without_retry(self):
        adb = Mock()
        with self.assertRaisesRegex(RuntimeError, 'navigation failed'):
            with fixture_tunnel(adb, '32768'):
                raise RuntimeError('navigation failed')
        self.assertEqual(adb.call_count, 2)

    def test_existing_mapping_failure_is_not_removed(self):
        adb = Mock(side_effect=RuntimeError('already bound'))
        with self.assertRaisesRegex(RuntimeError, 'already bound'):
            with fixture_tunnel(adb, '32768'):
                self.fail('Must not enter after mapping failure')
        self.assertEqual(adb.call_count, 1)

    def test_invalid_ports_never_reach_adb(self):
        adb = Mock()
        for port in ('0', '443', '65536', '32768/x', '３２７６８', '', None, 32768):
            with self.subTest(port=port), self.assertRaises(ValueError):
                with fixture_tunnel(adb, port):
                    self.fail('Invalid port accepted')
        adb.assert_not_called()
