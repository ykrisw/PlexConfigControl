import http.client
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler
from plexconfigcontrol.web import Web

class Quiet(WSGIRequestHandler):
    def log_message(self,*args): pass

class WebTests(unittest.TestCase):
    @patch('plexconfigcontrol.auth.ITERATIONS',1000)
    def test_http_auth_settings_history_logout(self):
        with tempfile.TemporaryDirectory() as d:
            app=Web(d); app.account.initialize('correct')
            event=app.history.add('BACKUP','SUCCESS','full log')
            server=make_server('127.0.0.1',0,app,handler_class=Quiet)
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port)
            def request(method,path,data=None,headers=None):
                h={'Content-Type':'application/json',**(headers or {})}
                connection.request(method,path,json.dumps(data) if data is not None else None,h)
                response=connection.getresponse(); body=json.loads(response.read())
                return response,body
            try:
                r,_=request('GET','/api/settings'); self.assertEqual(r.status,401)
                r,body=request('POST','/api/login',{'password':'correct'},{'X-PCC-Request':'1'})
                self.assertEqual(r.status,200)
                cookie=r.getheader('Set-Cookie'); self.assertIn('Secure; HttpOnly; SameSite=Strict',cookie)
                headers={'Cookie':cookie.split(';')[0]}
                r,_=request('POST','/api/settings',{'language':'pl'},headers); self.assertEqual(r.status,403)
                headers['X-CSRF-Token']=body['csrf']
                r,prefs=request('POST','/api/settings',{'language':'pl'},headers)
                self.assertEqual(prefs['language'],'pl')
                r,catalog=request('GET','/api/translations',headers=headers)
                self.assertEqual(catalog['settings'],'Ustawienia')
                r,_=request('POST','/api/history/clear',{'ids':[event],'confirmed':True},headers)
                self.assertEqual(r.status,200); self.assertIsNone(app.history.detail(event))
                r,_=request('POST','/api/logout',{},headers); self.assertEqual(r.status,200)
                r,_=request('GET','/api/settings',headers=headers); self.assertEqual(r.status,401)
            finally:
                connection.close(); server.shutdown(); server.server_close(); thread.join()
