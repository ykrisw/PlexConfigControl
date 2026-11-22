import hashlib
import importlib.util
from pathlib import Path
import ssl
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, mock_open, patch

spec=importlib.util.spec_from_file_location('qnap_api_reload',Path(__file__).resolve().parents[1]/'runtime/plexconfigcontrol/qnap_api.py')
api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)

class CertificateReloadTests(unittest.TestCase):
    def test_new_local_certificate_is_used_without_losing_session_or_retry(self):
        context=ssl.create_default_context();factory=Mock()
        connections=[]
        for cert in (b'old',b'new'):
            c=Mock();c.sock.getpeercert.return_value=cert
            c.getresponse.return_value.status=200;c.getresponse.return_value.read.return_value=b'<root/>'
            connections.append(c)
        factory.side_effect=connections
        client=api.QnapLocalReadOnlyApi(443,tls_context=context,connection_factory=factory,local_certificate_path='/etc/stunnel/stunnel.pem')
        client._session='fixture-session'
        contexts=[(context,hashlib.sha256(cert).hexdigest()) for cert in (b'old',b'new')]
        with patch('builtins.open',mock_open(read_data='public certificate fixture')),patch.object(api.os,'fstat',return_value=SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=0,st_size=20)),patch.object(api,'local_certificate_context',side_effect=contexts) as refresh:
            client.probe();client.probe()
        self.assertEqual(refresh.call_count,2);self.assertEqual(factory.call_count,2)
        self.assertEqual(client._session,'fixture-session')
        for c in connections:self.assertEqual(c.request.call_count,1)
    def test_missing_certificate_does_not_send_or_retry_request(self):
        factory=Mock();client=api.QnapLocalReadOnlyApi(443,connection_factory=factory,local_certificate_path='/etc/stunnel/stunnel.pem')
        with patch('builtins.open',side_effect=FileNotFoundError):
            with self.assertRaises(api.QnapApiError):client.probe()
        factory.assert_not_called()

class RealCertificateReloadTests(unittest.TestCase):
    def test_real_https_certificate_rotation_keeps_session(self):
        import http.server, subprocess, tempfile, threading
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('first','second'):
                subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=QNAP-fixture','-keyout',str(root/(name+'.key')),'-out',str(root/(name+'.crt'))],check=True,capture_output=True)
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200);self.end_headers();self.wfile.write(b'<root/>')
                def log_message(self,*args):pass
            client=None
            actual_open=open
            for name in ('first','second'):
                server=http.server.HTTPServer(('127.0.0.1',0),Handler)
                context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(root/(name+'.crt'),root/(name+'.key'))
                server.socket=context.wrap_socket(server.socket,server_side=True)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    if client is None:
                        client=api.QnapLocalReadOnlyApi(server.server_port,local_certificate_path='/etc/stunnel/stunnel.pem');client._session='fixture-session'
                    else:client.port=server.server_port
                    def local_open(path,*args,**kwargs):
                        return actual_open(root/(name+'.crt') if str(path)=='/etc/stunnel/stunnel.pem' else path,*args,**kwargs)
                    with patch('builtins.open',side_effect=local_open),patch.object(api.os,'fstat',return_value=SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=0,st_size=4096)):
                        client.probe()
                    self.assertEqual(client._session,'fixture-session')
                finally:server.shutdown();server.server_close();thread.join()
