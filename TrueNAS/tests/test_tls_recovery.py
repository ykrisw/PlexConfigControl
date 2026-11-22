"""Real TLS rotation and the offline execution-owner/panel boundary."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import io
import json
import os
from pathlib import Path
import socket
import socketserver
import ssl
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from plexconfigcontrol.transport import SecureWebSocket,build_client
from plexconfigcontrol.installer_trust import trusted_issuer_chain,public_certificates,make_leaf_pin,read_leaf_pin
from plexconfigcontrol.connection_errors import connection_code
from plexconfigcontrol.rpc import TrueNASConnectionError
from plexconfigcontrol.deferred_worker import DeferredWorker
from plexconfigcontrol.execution_ipc import ExecutionSocketServer
from plexconfigcontrol.runtime import Configuration,prepare
from plexconfigcontrol.installation import password_verifier


def certificate(issuer=None,expired=False):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost' if issuer else 'Test root')])
    now=datetime.now(timezone.utc)
    builder=x509.CertificateBuilder().subject_name(name).issuer_name(issuer[1].subject if issuer else name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=3)).not_valid_after(now+timedelta(days=-1 if expired else 30)).add_extension(x509.BasicConstraints(ca=issuer is None,path_length=None),critical=True)
    if issuer:builder=builder.add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False)
    builder=builder.add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),critical=False).add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key((issuer[0] if issuer else key).public_key()),critical=False).add_extension(x509.KeyUsage(digital_signature=True,content_commitment=False,key_encipherment=issuer is not None,data_encipherment=False,key_agreement=False,key_cert_sign=issuer is None,crl_sign=issuer is None,encipher_only=None,decipher_only=None),critical=True)
    cert=builder.sign(issuer[0] if issuer else key,hashes.SHA256())
    return key,cert


def pem(cert):return cert.public_bytes(serialization.Encoding.PEM).decode()


@contextmanager
def server(folder,identity):
    key,cert=identity;folder.mkdir()
    (folder/'cert').write_text(pem(cert));(folder/'key').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(folder/'cert',folder/'key')
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):pass
    with socketserver.ThreadingTCPServer(('127.0.0.1',0),Handler) as http:
        http.socket=context.wrap_socket(http.socket,server_side=True)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:yield http.server_address[1]
        finally:http.shutdown();thread.join()


def connector(url,**kwargs):
    from urllib.parse import urlsplit
    parsed=urlsplit(url)
    raw=socket.create_connection(('127.0.0.1',parsed.port),timeout=3)
    try:return kwargs['sslopt']['context'].wrap_socket(raw,server_hostname=parsed.hostname)
    except BaseException:raw.close();raise


class TLSRecovery(unittest.TestCase):
    def test_real_renewal_rotated_ca_and_wrong_host(self):
        root=certificate();newroot=certificate()
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);ca=folder/'ca.pem';ca.write_text(pem(root[1]))
            transport=SecureWebSocket(str(ca),connector=connector)
            for number,leaf in enumerate((certificate(root),certificate(root))):
                with server(folder/str(number),leaf) as port:
                    transport(f'wss://localhost:{port}/api/current').close()
                    with self.assertRaises(ssl.SSLCertVerificationError) as error:transport(f'wss://wrong.example:{port}/api/current')
                    self.assertEqual(connection_code(error.exception),'TLS_HOSTNAME')
            with server(folder/'new',certificate(newroot)) as port:
                with self.assertRaises(ssl.SSLCertVerificationError) as error:transport(f'wss://localhost:{port}/api/current')
                self.assertEqual(connection_code(error.exception),'TLS_UNTRUSTED')
                replacement=ca.with_suffix('.new');replacement.write_text(pem(newroot[1]));os.replace(replacement,ca)
                transport(f'wss://localhost:{port}/api/current').close()
            with server(folder/'expired',certificate(newroot,expired=True)) as port:
                with self.assertRaises(ssl.SSLCertVerificationError) as error:transport(f'wss://localhost:{port}/api/current')
                self.assertEqual(connection_code(error.exception),'TLS_EXPIRED')

    def test_candidate_roots_must_actually_sign_the_ssh_authenticated_leaf(self):
        root=certificate();other=certificate();leaf=certificate(root)
        self.assertIsNone(trusted_issuer_chain(pem(leaf[1]),pem(other[1])))
        self.assertEqual(trusted_issuer_chain(pem(leaf[1]),pem(other[1])+pem(root[1])),pem(root[1]))
        with self.assertRaises(ValueError):public_certificates(pem(root[1])+'-----BEGIN PRIVATE KEY-----')

    def test_exact_certificate_authenticated_over_ssh_can_be_pinned(self):
        root=certificate();leaf=certificate(root)
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);ca=folder/'pin.pem';ca.write_text(pem(leaf[1]))
            transport=SecureWebSocket(str(ca),connector=connector)
            with server(folder/'expected',leaf) as port:transport(f'wss://localhost:{port}/api/current').close()
            with server(folder/'different',certificate(root)) as port:
                with self.assertRaises(ssl.SSLCertVerificationError):transport(f'wss://localhost:{port}/api/current')

    def test_rpc_diagnostics_do_not_leak_transport_or_credentials(self):
        client=build_client('wss://localhost/api/current','user','secret','/missing/public-ca')
        with self.assertRaises(TrueNASConnectionError) as error:client.call('app.query')
        self.assertEqual(error.exception.code,'TLS_CA_UNAVAILABLE')
        self.assertNotIn('/missing',str(error.exception));self.assertNotIn('secret',str(error.exception))

    def test_local_panel_and_journal_are_ready_with_untrusted_api_and_no_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);state=base/'state';archives=base/'archives';state.mkdir();archives.mkdir()
            api=Mock();api.call.side_effect=TrueNASConnectionError('TLS_UNTRUSTED')
            factory=Mock(side_effect=AssertionError('No storage coordinator should be created for a local read'))
            owner=DeferredWorker(state,archives,api,factory);owner.reconcile_startup()
            sock=base/'worker.sock'
            # Exercise the real dispatcher and operational web app without requiring
            # Unix-socket permission in restricted local test environments.
            ipc=object.__new__(ExecutionSocketServer);ipc.gateway=owner.gateway();ipc.worker=owner
            def bridge(adapter,action,data):
                binding=[[value.stat().st_dev,value.stat().st_ino] for value in (adapter.state,adapter.archives)]
                return ipc.dispatch({'action':action,'data':data,'binding':binding})
            with patch('plexconfigcontrol.execution_ipc.ExecutionSocketClient._call',bridge):
                app,_,_=prepare(Configuration(state,'localhost',archives=archives,execution_socket=sock,execution_uid=os.geteuid()),password_verifier('dummy-fixture-password'))
                def request(path,cookie=None):
                    response=[];env={'REQUEST_METHOD':'GET','PATH_INFO':path,'wsgi.input':io.BytesIO(b'')}
                    if cookie:env['HTTP_COOKIE']=cookie
                    body=b''.join(app(env,lambda status,headers:response.append(status)))
                    return response[0],body
                self.assertEqual(request('/healthz')[0],'200 OK')
                token,_=app.web.sessions.create();status,body=request('/api/status','pcc_session='+token)
                self.assertEqual(status,'200 OK');self.assertEqual(json.loads(body)['error_code'],'TLS_UNTRUSTED')
                self.assertEqual(request('/api/history','pcc_session='+token)[0],'200 OK')
                self.assertEqual(request('/assets/connection-notice.mjs')[0],'200 OK')
                self.assertIsNone(owner.gateway().status());factory.assert_not_called()
            owner.close()

    def test_installer_automatically_uses_the_ssh_authenticated_certificate(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('installer_tls_fixture',Path(__file__).resolve().parents[1]/'deploy/install_pl.py')
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        root=certificate();leaf=certificate(root)
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            with server(folder/'nas',leaf) as port:
                source=folder/'registered.pem'
                source.write_bytes(pem(leaf[1]).encode()+leaf[0].private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
                api=Mock();api.call.return_value={'certificate_path':str(source)}
                with patch('plexconfigcontrol.installer_trust.desktop_candidates',return_value=pem(root[1])):
                    result=installer.verified_ca(api,{'ui_httpsport':port,'ui_certificate':{'id':3}},'127.0.0.1','localhost',folder/'saved-ca.pem',None)
                self.assertEqual(result,pem(root[1]))
                self.assertNotIn('PRIVATE KEY',result)
                with patch('plexconfigcontrol.installer_trust.desktop_candidates',return_value=''):
                    result=installer.verified_ca(api,{'ui_httpsport':port,'ui_certificate':{'id':3}},'127.0.0.1','localhost',folder/'saved-ca.pem',None)
                self.assertIn('BEGIN CERTIFICATE',result);self.assertNotIn('PRIVATE KEY',result)

    def test_stock_truenas_certificate_without_san_uses_ssh_authenticated_pin(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('installer_tls_stock',Path(__file__).resolve().parents[1]/'deploy/install_pl.py')
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        stock=certificate()  # Self-signed, valid, no subjectAltName.
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            source=folder/'public.pem';source.write_text(pem(stock[1]))
            api=Mock();api.call.return_value={'certificate_path':str(source)}
            with server(folder/'nas',stock) as port:
                with patch('plexconfigcontrol.installer_trust.desktop_candidates',return_value=''):
                    chosen=installer.verified_ca(api,{'ui_httpsport':port,'ui_certificate':{'id':1}},'127.0.0.1','127.0.0.1',folder/'saved.pem',None)
                self.assertIsNotNone(read_leaf_pin(chosen))
                self.assertNotIn('PRIVATE KEY',chosen)
                self.assertEqual(chosen,make_leaf_pin(pem(stock[1])))
                with tempfile.TemporaryDirectory() as second:
                    ca=Path(second)/'pinned.pem';ca.write_text(chosen)
                    transport=SecureWebSocket(str(ca),connector=connector)
                    with server(folder/'different',certificate()) as other_port:
                        with self.assertRaises(ssl.SSLError):
                            transport(f'wss://127.0.0.1:{other_port}/api/current')
