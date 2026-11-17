"""Disposable HTTPS app fixture for macOS/Safari tests; never a user's NAS."""
import io
import ssl
import tarfile
import tempfile
import threading
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server

from plexconfigcontrol.archives import REQUIRED
from plexconfigcontrol.installation import password_verifier
from plexconfigcontrol.runtime import Configuration, prepare


class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@contextmanager
def apple_fixture():
    with tempfile.TemporaryDirectory(prefix='pcc-apple-') as temporary:
        root = Path(temporary)
        archives = root/'archives'
        archives.mkdir()
        (archives/'Logs').mkdir()
        (archives/'Logs'/'fixture-permanent.log').write_text('Permanent CI log must survive History clearing.')
        for day in range(1, 14):
            with tarfile.open(archives/f'TrueNASPlexConfig_2026.10.{day:02d}_10.30.00.tar.gz', 'w:gz') as archive:
                for name in REQUIRED:
                    member = tarfile.TarInfo(name)
                    member.size = 4
                    archive.addfile(member, io.BytesIO(b'test'))
        password = 'ci-apple-only-password'
        app, cert, key = prepare(Configuration(root/'state', '127.0.0.1', archives=archives), password_verifier(password))
        for index in range(20):
            app.web.history.add('BACKUP' if index%2 else 'RESTORE', 'SUCCESS', 'CI Apple fixture '+str(index))
        requests = []
        def monitored(environ, start_response):
            def respond(status, headers, exc_info=None):
                if environ.get('PATH_INFO','').startswith('/api/'):
                    requests.append({'path':environ['PATH_INFO'], 'status':status,
                        'session_cookie_received':'pcc_session=' in environ.get('HTTP_COOKIE',''),
                        'session_cookie_set':any(name.lower()=='set-cookie' for name,value in headers)})
                return start_response(status,headers,exc_info)
            return app(environ,respond)
        server = make_server('127.0.0.1', 0, monitored, server_class=ThreadedServer, handler_class=QuietHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'https://127.0.0.1:{server.server_port}'
        try:
            # TLS verification is independent of the browser's trust setup.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(cert))))
            with opener.open(url+'/healthz', timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError('Apple fixture HTTPS health check failed')
            yield dict(root=root, archives=archives, state=root/'state', app=app.web,
                       url=url, cert=cert, password=password, requests=requests)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)
