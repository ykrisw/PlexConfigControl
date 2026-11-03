import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.archives import REQUIRED
from plexconfigcontrol.web import Web
from plexconfigcontrol.operations import Phase
from plexconfigcontrol.publication_intent import record

NAME='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'

class RestoreEndpointTests(unittest.TestCase):
    def test_validation_auth_csrf_wait_cancel_and_invalid_archive(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); dest=root/'backup'; dest.mkdir(); calls=[]
            app=Web(root/'state',dest,truenas_api=lambda *args: calls.append(args))
            token,csrf=app.sessions.create()
            def request(path,data,authenticated=True,csrf_value=csrf):
                raw=json.dumps(data).encode(); status=[]
                env={'REQUEST_METHOD':'POST','PATH_INFO':path,'CONTENT_TYPE':'application/json',
                     'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),
                     'HTTP_COOKIE':'pcc_session='+token if authenticated else '',
                     'HTTP_X_CSRF_TOKEN':csrf_value}
                result=b''.join(app(env,lambda code,headers:status.append(code)))
                return status[0],json.loads(result)
            endpoint='/api/restore/validate'
            self.assertEqual(request(endpoint,{'archive':NAME},False)[0],'401 Unauthorized')
            self.assertEqual(request(endpoint,{'archive':NAME},csrf_value='bad')[0],'403 Forbidden')
            self.assertEqual(request(endpoint,{'archive':'../../other'})[0],'400 Bad Request')
            with tarfile.open(dest/NAME,'w:gz') as archive:
                for name in REQUIRED:
                    member=tarfile.TarInfo(name); member.size=4
                    archive.addfile(member,io.BytesIO(b'test'))
            code,result=request(endpoint,{'archive':NAME})
            self.assertEqual(code,'200 OK')
            self.assertEqual(result['phase'],'WAITING_FOR_PLEX_STOP')
            self.assertEqual(request(endpoint,{'archive':NAME})[0],'409 Conflict')
            self.assertEqual(request('/api/restore/cancel',{})[0],'200 OK')
            with app.operation_store.transaction() as op: self.assertEqual(op.phase,Phase.IDLE)
            (dest/NAME).write_bytes(b'broken')
            code,result=request(endpoint,{'archive':NAME})
            self.assertEqual(code,'422 Unprocessable Entity')
            self.assertEqual(result['validation'],'FAILED')
            self.assertIn('Corrupt',result['error'])
            record(root/'state','.pcc-'+'a'*32+'.tmp',NAME)
            self.assertEqual(request(endpoint,{'archive':NAME})[0],'409 Conflict')
            self.assertEqual(calls,[])  # No host operation, start, stop or snapshot.
