import ssl
import unittest
from plexconfigcontrol.transport import SecureWebSocket,build_client

class TransportTests(unittest.TestCase):
    def test_verification_timeout_redirect_and_proxy_policy(self):
        calls=[]
        def connector(url,**kwargs): calls.append((url,kwargs)); return 'connection'
        transport=SecureWebSocket(timeout=12,connector=connector)
        self.assertEqual(transport('wss://nas/api/current'),'connection')
        options=calls[0][1]; context=options['sslopt']['context']
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        self.assertEqual(options['redirect_limit'],0)
        self.assertEqual(options['timeout'],12)
        self.assertEqual(options['http_no_proxy'],['*'])
        with self.assertRaises(ValueError): transport('ws://nas/api/current')
    def test_missing_credentials_or_ca_fail_closed(self):
        with self.assertRaises(ValueError): build_client('wss://nas/api/current','user','')
        with self.assertRaises(OSError): SecureWebSocket('/nonexistent/pcc-ca.pem')
