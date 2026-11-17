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
            self.assertIsInstance(rows[0]['modified_ns'],str)
            self.assertEqual(int(rows[0]['modified_ns']),(backup/NAME).stat().st_mtime_ns)
            data={'archives':rows,'confirmed':True}
            status,_=request('/api/archives/delete',data,'wrong'); self.assertTrue(status.startswith('403'))
            with operation_lock(root/'state'):
                status,_=request('/api/archives/delete',data); self.assertTrue(status.startswith('409'))
            status,body=request('/api/archives/delete',data)
            self.assertEqual(status,'200 OK'); self.assertEqual(body['deleted'],[NAME])
            self.assertEqual(log.read_text(),'keep')
            self.assertEqual(app.history.list()[0]['kind'],'ARCHIVE_DELETE')
            status,_=request('/api/archives/delete',data); self.assertTrue(status.startswith('409'))

    def test_capabilities_and_disabled_deletion_are_enforced_on_server(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);backup=root/'archives';backup.mkdir();archive=backup/NAME;archive.write_bytes(b'keep')
            app=Web(root/'state',backup,archive_deletion_enabled=False)
            token,csrf=app.sessions.create()
            def request(path,body=None):
                data=json.dumps(body).encode() if body is not None else b'';responses=[]
                result=b''.join(app({'REQUEST_METHOD':'POST' if body is not None else 'GET','PATH_INFO':path,
                    'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(data)),'wsgi.input':io.BytesIO(data),
                    'HTTP_COOKIE':'pcc_session='+token,'HTTP_X_CSRF_TOKEN':csrf},lambda code,headers:responses.append(code)))
                return responses[0],json.loads(result)
            status,capabilities=request('/api/capabilities')
            self.assertEqual(status,'200 OK');self.assertFalse(capabilities['archive_delete'])
            self.assertFalse(capabilities['backup_create']);self.assertFalse(capabilities['restore_execute'])
            _,rows=request('/api/archives')
            status,_=request('/api/archives/delete',{'archives':rows,'confirmed':True})
            self.assertEqual(status,'403 Forbidden');self.assertEqual(archive.read_bytes(),b'keep')

    def test_wire_identity_preserves_uint64_values_and_rejects_imprecise_fields(self):
        from plexconfigcontrol.web import archive_wire,archive_integer
        large=2**63+123
        row=archive_wire({'name':NAME,'size':5,'device':1,'inode':large,'modified_ns':large+1})
        through_browser=json.loads(json.dumps(row))
        self.assertEqual(archive_integer(through_browser['inode']),large)
        self.assertEqual(archive_integer(through_browser['modified_ns']),large+1)
        for bad in (True,-1,1.5,'1e18','01','-1','18446744073709551616'):
            with self.assertRaises(ValueError):archive_integer(bad)
