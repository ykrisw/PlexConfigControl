"""Check the portable UI fixture's TLS/HTTP boundaries without a browser/NAS."""
import json
import ssl
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

# Also support unittest invoked with explicit package names from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desktop_fixture import desktop_fixture


class DesktopFixtureTests(unittest.TestCase):
    def test_verified_https_requires_fixture_signin_and_csrf(self):
        with desktop_fixture() as (api, url, cert):
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),
                urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(cert))))
            def request(path, data=None, headers=None):
                req=urllib.request.Request(url+path, data=json.dumps(data).encode() if data is not None else None,headers=headers or {})
                return opener.open(req,timeout=5)
            with request('/') as response:
                self.assertIn(b'panel-app.mjs',response.read())
            with self.assertRaises(urllib.error.HTTPError) as failure:
                request('/api/settings')
            self.assertEqual(failure.exception.code,401)
            with request('/api/login', {'password':'fixture-only-password'}) as response:
                self.assertTrue(json.load(response)['authenticated'])
            with self.assertRaises(urllib.error.HTTPError) as failure:
                request('/api/settings',{'theme':'Dark'})
            self.assertEqual(failure.exception.code,403)
            with request('/api/settings',{'theme':'Dark'},{'X-CSRF-Token':'fixture-only-csrf'}) as response:
                self.assertEqual(json.load(response)['theme'],'Dark')
            with request('/api/archives') as response:self.assertEqual(len(json.load(response)),13)
            with request('/api/history') as response:self.assertEqual(len(json.load(response)),20)
            for path in ('/assets/../desktop_fixture.py','/assets/missing.mjs'):
                with self.subTest(path=path),self.assertRaises(urllib.error.HTTPError) as failure:
                    request(path)
                self.assertEqual(failure.exception.code,404)
            self.assertEqual(api.posts,[])
            with request('/api/logout', {}, {'X-CSRF-Token':'fixture-only-csrf'}) as response:
                self.assertFalse(json.load(response)['authenticated'])
            self.assertFalse(api.authenticated)


    def test_tls_fixture_accepts_parallel_connection_burst_before_handshake(self):
        import socket
        from urllib.parse import urlsplit
        with desktop_fixture() as (_,url,_):
            address=urlsplit(url)
            sockets=[]
            try:
                for _ in range(16):
                    sockets.append(socket.create_connection((address.hostname,address.port),timeout=1))
                self.assertEqual(len(sockets),16)
            finally:
                for connection in sockets:connection.close()
