import io
import json
import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.web import Web
from plexconfigcontrol.locking import operation_lock

NAME='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'
class ArchiveEndpointTests(unittest.TestCase):
    def test_listing_delete_confirmation_csrf_and_busy(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); backup=root/'Plex Config'; backup.mkdir()
            (backup/NAME).write_bytes(b'archive'); (backup/'Logs').mkdir()
            log=backup/'Logs'/'Backup.log'; log.write_text('keep')
            app=Web(root/'state',backup); token,csrf=app.sessions.create()
            def request(path,data=None,csrf_value=csrf):
                body=json.dumps(data).encode() if data is not None else b''
                env={'REQUEST_METHOD':'POST' if data is not None else 'GET',
                     'PATH_INFO':path,'CONTENT_TYPE':'application/json',
                     'CONTENT_LENGTH':str(len(body)),'wsgi.input':io.BytesIO(body),
                     'HTTP_COOKIE':'pcc_session='+token,'HTTP_X_CSRF_TOKEN':csrf_value}
                status=[]
                output=b''.join(app(env,lambda code,headers:status.append(code)))
                return status[0],json.loads(output)
            status,rows=request('/api/archives'); self.assertEqual(status,'200 OK')
            data={'archives':rows,'confirmed':True}
            status,_=request('/api/archives/delete',data,'wrong'); self.assertTrue(status.startswith('403'))
            with operation_lock(root/'state'):
                status,_=request('/api/archives/delete',data); self.assertTrue(status.startswith('409'))
            status,body=request('/api/archives/delete',data)
            self.assertEqual(status,'200 OK'); self.assertEqual(body['deleted'],[NAME])
            self.assertEqual(log.read_text(),'keep')
            self.assertEqual(app.history.list()[0]['kind'],'ARCHIVE_DELETE')
            status,_=request('/api/archives/delete',data); self.assertTrue(status.startswith('409'))
