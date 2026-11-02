import io
import json
import tempfile
import unittest
from unittest.mock import patch
from plexconfigcontrol.web import Web

class PasswordEndpointTests(unittest.TestCase):
    @patch('plexconfigcontrol.auth.ITERATIONS',1000)
    def test_password_change_requires_auth_csrf_and_matching_fields(self):
        with tempfile.TemporaryDirectory() as d:
            app=Web(d); app.account.initialize('old-secret')
            token,csrf=app.sessions.create(); second,_=app.sessions.create()
            def request(data,session=token,csrf_token=csrf):
                body=json.dumps(data).encode(); status=[]
                env={'REQUEST_METHOD':'POST','PATH_INFO':'/api/account/password',
                     'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(body)),
                     'wsgi.input':io.BytesIO(body),'HTTP_COOKIE':'pcc_session='+session,
                     'HTTP_X_CSRF_TOKEN':csrf_token}
                result=b''.join(app(env,lambda code,headers:status.append(code)))
                return status[0],json.loads(result)
            data={'current_password':'old-secret','new_password':'new-secret','confirm_new_password':'new-secret'}
            self.assertTrue(request(data,session='invalid')[0].startswith('401'))
            self.assertTrue(request(data,csrf_token='wrong')[0].startswith('403'))
            self.assertTrue(request({**data,'confirm_new_password':'different'})[0].startswith('400'))
            self.assertTrue(request({**data,'current_password':'wrong'})[0].startswith('403'))
            self.assertTrue(app.sessions.authenticated(token))
            status,result=request(data)
            self.assertEqual(status,'200 OK'); self.assertTrue(result['sign_in_required'])
            self.assertFalse(app.sessions.authenticated(token)); self.assertFalse(app.sessions.authenticated(second))
            self.assertTrue(app.account.login('new-secret')['authenticated'])
            event=app.history.detail(app.history.list()[0]['id'])
            self.assertNotIn('old-secret',event['log']); self.assertNotIn('new-secret',event['log'])
