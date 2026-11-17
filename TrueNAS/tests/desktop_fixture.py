"""Portable HTTPS UI fixture. All API data is synthetic; no NAS/backend imports."""
import json
import ssl
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from execution_ui_e2e import FixtureAPI, STATIC


class DesktopServer(ThreadingHTTPServer):
    # Opera/Windows opens a burst of parallel TLS asset connections. Keep the
    # disposable fixture's listen backlog bounded but above the default five.
    request_queue_size = 64


class DesktopAPI(FixtureAPI):
    def __init__(self):
        super().__init__('backup', 'en', 'system')
        self.authenticated = False
        self.preferences = {'theme':'System', 'language':'en', 'timezone':'Europe/London'}
        self.rows = [dict(self.rows[0], name=f'TrueNASPlexConfig_2026.10.{day:02d}_10.30.00.tar.gz', inode=str(day)) for day in range(1, 14)]
        self.events = [dict(id=i, kind='BACKUP' if i%2 else 'RESTORE', status='SUCCESS', created='2026-11-03T04:15:35Z', message='Synthetic desktop fixture') for i in range(1,21)]
        self.calls = []

    def handle(self, method, path, payload=None, query=''):
        self.calls.append((method, path))
        if path == '/api/login' and method == 'POST':
            if payload != {'password':'fixture-only-password'}:
                return 401, {'error':'Incorrect fixture password'}
            self.authenticated = True
            return 200, {'authenticated':True, 'csrf':'fixture-only-csrf'}
        if not self.authenticated:
            return 401, {'error':'Fixture sign-in required'}
        if path == '/api/session':
            return 200, {'authenticated':True, 'csrf':'fixture-only-csrf'}
        if path == '/api/settings':
            if method == 'POST':
                self.preferences.update(payload)
            return 200, self.preferences
        if path == '/api/account/photo/status':
            return 200, {'present':False, 'revision':None}
        if path == '/api/history': return 200, self.events
        if path == '/api/logout' and method == 'POST':
            self.authenticated = False
            return 200, {'authenticated':False}
        return super().handle(method, path, payload, query)


@contextmanager
def desktop_fixture():
    # Kept outside the product: this server is not an installable application.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import ipaddress

    api = DesktopAPI()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def respond(self, status, content, content_type='application/json'):
            body = json.dumps(content).encode() if content_type=='application/json' else content
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == '/':
                return self.respond(200, (STATIC/'index.html').read_bytes(), 'text/html; charset=utf-8')
            if url.path.startswith('/assets/'):
                name = url.path.removeprefix('/assets/')
                path = STATIC/name
                if Path(name).name != name or path.suffix not in ('.mjs','.css') or not path.is_file():
                    return self.respond(404, {'error':'No fixture asset'})
                return self.respond(200, path.read_bytes(), 'text/javascript' if path.suffix=='.mjs' else 'text/css')
            status, result = api.handle('GET', url.path, query=url.query)
            self.respond(status, result)
        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 16384: raise ValueError('Fixture body size')
                payload = json.loads(self.rfile.read(size))
            except (ValueError, OSError):
                return self.respond(400, {'error':'Invalid fixture body'})
            url = urlsplit(self.path)
            if url.path != '/api/login' and self.headers.get('X-CSRF-Token') != 'fixture-only-csrf':
                return self.respond(403, {'error':'Fixture CSRF missing'})
            status, result = api.handle('POST', url.path, payload, url.query)
            self.respond(status, result)

    with tempfile.TemporaryDirectory(prefix='pcc-desktop-ui-') as temporary:
        root = Path(temporary)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Disposable PCC desktop UI fixture')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(key, hashes.SHA256()))
        cert_path = root/'fixture.crt'; key_path = root/'fixture.key'
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        server = DesktopServer(('127.0.0.1',0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield api, f'https://127.0.0.1:{server.server_port}', cert_path
        finally:
            server.shutdown();server.server_close();thread.join(5)
