import io
import json
import tempfile
import unittest
from unittest.mock import patch
from plexconfigcontrol.web import Web

class LoginHistoryTests(unittest.TestCase):
    @patch('plexconfigcontrol.auth.ITERATIONS',1000)
    def test_failed_login_and_lockout_are_recorded_without_password(self):
        with tempfile.TemporaryDirectory() as d:
            app=Web(d); app.account.initialize('correct-secret')
            def request(path,data,cookie='',csrf=''):
                body=json.dumps(data).encode(); codes=[]
                env={'REQUEST_METHOD':'POST','PATH_INFO':path,'CONTENT_TYPE':'application/json',
                     'CONTENT_LENGTH':str(len(body)),'wsgi.input':io.BytesIO(body),
                     'HTTP_X_PCC_REQUEST':'1','HTTP_COOKIE':cookie,'HTTP_X_CSRF_TOKEN':csrf}
                result=json.loads(b''.join(app(env,lambda code,headers:codes.append(code))))
                return codes[0],result
            for _ in range(5): status,result=request('/api/login',{'password':'wrong-secret'})
            self.assertEqual(status,'401 Unauthorized'); self.assertGreater(result['blocked_until'],0)
            rows=app.history.list(); self.assertEqual(len(rows),5)
            for row in rows:
                event=app.history.detail(row['id'])
                self.assertEqual(event['kind'],'LOGIN')
                self.assertNotIn('wrong-secret',event['log']); self.assertNotIn('correct-secret',event['log'])
            token,csrf=app.sessions.create()
            status,event=request('/api/history/detail',{'id':rows[0]['id']},'pcc_session='+token,csrf)
            self.assertEqual(status,'200 OK'); self.assertIn('Blocked until',event['log'])
            app.history.clear([rows[0]['id']])
            status,_=request('/api/history/detail',{'id':rows[0]['id']},'pcc_session='+token,csrf)
            self.assertEqual(status,'404 Not Found')
