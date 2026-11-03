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

    def test_transitive_asset_network_change_can_retry_before_login_is_ready(self):
        from types import SimpleNamespace
        handlers={};attempts=[]
        page=Mock()
        page.on.side_effect=lambda event,callback:handlers.__setitem__(event,callback)
        def navigate(url):
            attempts.append(url)
            if len(attempts)==1:
                request=SimpleNamespace(method='GET',url=url+'/assets/panel-app.mjs',failure='net::ERR_NETWORK_CHANGED')
                handlers['requestfailed'](request)
            return 'loaded'
        page.goto.side_effect=navigate
        page.locator.return_value.wait_for.side_effect=[TimeoutError('Login never mounted'),None]
        pause=Mock()
        self.assertEqual(open_fixture(page,'https://127.0.0.1:12345',pause=pause,ready_selector='.pcc-login input'),'loaded')
        self.assertEqual(page.goto.call_count,2)
        self.assertEqual(page.remove_listener.call_count,4)
        pause.assert_called_once_with(.5)

    def test_bootstrap_retry_never_reloads_after_a_write_or_for_unrelated_failures(self):
        from types import SimpleNamespace
        cases=(('POST','https://127.0.0.1:12345/assets/panel-app.mjs','net::ERR_NETWORK_CHANGED'),
               ('GET','https://other.example/assets/panel-app.mjs','net::ERR_NETWORK_CHANGED'),
               ('GET','https://127.0.0.1:12345/api/status','net::ERR_NETWORK_CHANGED'),
               ('GET','https://127.0.0.1:12345/assets/panel-app.mjs','net::ERR_CONNECTION_REFUSED'))
        for method,url,failure in cases:
            with self.subTest(method=method,url=url,failure=failure):
                handlers={};page=Mock();page.on.side_effect=lambda event,callback:handlers.__setitem__(event,callback)
                def navigate(_):
                    request=SimpleNamespace(method=method,url=url,failure=failure)
                    handlers['request'](request);handlers['requestfailed'](request)
                page.goto.side_effect=navigate;page.locator.return_value.wait_for.side_effect=TimeoutError('not mounted')
                with self.assertRaises(TimeoutError):open_fixture(page,'https://127.0.0.1:12345',pause=Mock(),ready_selector='.pcc-login input')
                self.assertEqual(page.goto.call_count,1)
                self.assertEqual(page.remove_listener.call_count,2)

    def test_even_matching_asset_failure_does_not_retry_if_any_mutation_was_sent(self):
        from types import SimpleNamespace
        handlers={};page=Mock();page.on.side_effect=lambda event,callback:handlers.__setitem__(event,callback)
        def navigate(_):
            handlers['request'](SimpleNamespace(method='POST'))
            handlers['requestfailed'](SimpleNamespace(method='GET',url='https://127.0.0.1:12345/assets/panel-app.mjs',failure='net::ERR_NETWORK_CHANGED'))
        page.goto.side_effect=navigate;page.locator.return_value.wait_for.side_effect=TimeoutError('not mounted')
        with self.assertRaises(TimeoutError):open_fixture(page,'https://127.0.0.1:12345',pause=Mock(),ready_selector='.pcc-login input')
        self.assertEqual(page.goto.call_count,1)
