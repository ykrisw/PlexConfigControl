import unittest
from unittest.mock import Mock
from browser_navigation import open_fixture


class BrowserNavigationTests(unittest.TestCase):
    def test_only_transient_fixture_get_navigation_is_retried(self):
        page=Mock();page.goto.side_effect=[RuntimeError('net::ERR_NETWORK_CHANGED'),'loaded'];pause=Mock()
        self.assertEqual(open_fixture(page,'https://127.0.0.1:12345',pause=pause),'loaded')
        self.assertEqual(page.goto.call_count,2);pause.assert_called_once_with(.5)
        page.goto.reset_mock();page.goto.side_effect=RuntimeError('application failure')
        with self.assertRaises(RuntimeError):open_fixture(page,'https://127.0.0.1:12345',pause=pause)
        self.assertEqual(page.goto.call_count,1)

    def test_retries_are_bounded_and_never_target_an_api_or_remote_host(self):
        page=Mock();page.goto.side_effect=RuntimeError('net::ERR_NETWORK_CHANGED');pause=Mock()
        with self.assertRaises(RuntimeError):open_fixture(page,'https://localhost:12345/',pause=pause)
        self.assertEqual(page.goto.call_count,3)
        for url in ('https://192.168.1.120','https://127.0.0.1/api/logout','http://localhost:12345','https://localhost/?action=restore'):
            with self.assertRaises(ValueError):open_fixture(page,url,pause=pause)
