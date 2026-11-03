import io
import json
import tempfile
import unittest
from plexconfigcontrol.web import Web
from plexconfigcontrol.profile_photo import MAX_UPLOAD
from test_profile_photo import picture


class PhotoEndpointTests(unittest.TestCase):
    def test_authenticated_photo_lifecycle_and_confirmation_identity(self):
        with tempfile.TemporaryDirectory() as d:
            app=Web(d);token,csrf=app.sessions.create()
            def request(path,body=None,raw=None,session=token,csrf_value=csrf):
                data=raw if raw is not None else json.dumps(body).encode() if body is not None else b''
                response=[]
                env={'REQUEST_METHOD':'POST' if raw is not None or body is not None else 'GET',
                    'PATH_INFO':path,'CONTENT_TYPE':'application/octet-stream' if raw is not None else 'application/json',
                    'CONTENT_LENGTH':str(len(data)),'wsgi.input':io.BytesIO(data),
                    'HTTP_COOKIE':'pcc_session='+session,'HTTP_X_CSRF_TOKEN':csrf_value}
                result=b''.join(app(env,lambda code,headers:response.append((code,dict(headers)))))
                return *response[0],result
            self.assertEqual(request('/api/account/photo')[0],'404 Not Found')
            self.assertEqual(request('/api/account/photo',raw=picture(),csrf_value='wrong')[0],'403 Forbidden')
            status,_,data=request('/api/account/photo',raw=picture());self.assertEqual(status,'200 OK')
            first=json.loads(data)
            status,headers,data=request('/api/account/photo')
            self.assertEqual(status,'200 OK');self.assertEqual(headers['Content-Type'],'image/png')
            self.assertEqual(headers['X-Content-Type-Options'],'nosniff');self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(request('/api/account/photo',session='invalid')[0],'401 Unauthorized')
            self.assertEqual(request('/api/account/photo',raw=b'invalid')[0],'422 Unprocessable Entity')
            self.assertEqual(request('/api/account/photo/remove',body={'revision':first['revision']})[0],'400 Bad Request')
            request('/api/account/photo',raw=picture('blue'))
            self.assertEqual(request('/api/account/photo/remove',body={'confirmed':True,'revision':first['revision']})[0],'409 Conflict')
            _,_,current=request('/api/account/photo/status');revision=json.loads(current)['revision']
            self.assertEqual(request('/api/account/photo/remove',body={'confirmed':True,'revision':revision})[0],'200 OK')
            self.assertEqual(request('/api/account/photo')[0],'404 Not Found')

    def test_unauthenticated_invalid_csrf_and_oversized_uploads_do_not_read_the_body(self):
        class ForbiddenRead:
            def read(self,*args):raise AssertionError('Upload body must not be read')
        with tempfile.TemporaryDirectory() as d:
            app=Web(d);token,csrf=app.sessions.create()
            for session,csrf_value,size,expected in [('invalid',csrf,10,'401'),(token,'wrong',10,'403'),(token,csrf,MAX_UPLOAD+1,'413')]:
                responses=[]
                app({'REQUEST_METHOD':'POST','PATH_INFO':'/api/account/photo','CONTENT_TYPE':'application/octet-stream',
                    'CONTENT_LENGTH':str(size),'wsgi.input':ForbiddenRead(),'HTTP_COOKIE':'pcc_session='+session,
                    'HTTP_X_CSRF_TOKEN':csrf_value},lambda status,headers:responses.append(status))
                self.assertTrue(responses[0].startswith(expected))
