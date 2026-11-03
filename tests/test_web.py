import http.client
import io
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler
from plexconfigcontrol.web import Web
from plexconfigcontrol.publication_intent import record

class Quiet(WSGIRequestHandler):
    def log_message(self,*args): pass

class WebTests(unittest.TestCase):
    @patch('plexconfigcontrol.auth.ITERATIONS',1000)
    def test_password_change_revokes_every_session_after_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            app=Web(d); app.account.initialize('old-password')
            first,csrf=app.sessions.create(); second,_=app.sessions.create()
            def change(current,new,confirmation):
                data=json.dumps({'current_password':current,'new_password':new,
                                 'confirm_new_password':confirmation}).encode()
                responses=[]
                body=b''.join(app({'REQUEST_METHOD':'POST','PATH_INFO':'/api/account/password',
                    'HTTP_COOKIE':'pcc_session='+first,'HTTP_X_CSRF_TOKEN':csrf,
                    'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(data)),
                    'wsgi.input':io.BytesIO(data)},
                    lambda status,headers:responses.append((status,dict(headers)))))
                return responses[0],json.loads(body)
            (status,_),_=change('old-password','new-password','different')
            self.assertEqual(status,'400 Bad Request')
            self.assertTrue(app.sessions.authenticated(first))
            (status,headers),body=change('old-password','new-password','new-password')
            self.assertEqual(status,'200 OK')
            self.assertEqual(body,{'changed':True,'sign_in_required':True})
            self.assertIn('Max-Age=0',headers['Set-Cookie'])
            self.assertFalse(app.sessions.authenticated(first))
            self.assertFalse(app.sessions.authenticated(second))
            self.assertFalse(app.account.login('old-password')['authenticated'])
            self.assertTrue(app.account.login('new-password')['authenticated'])

    def test_panel_assets_have_correct_mime_types(self):
        with tempfile.TemporaryDirectory() as d:
            app=Web(d)
            for name in ('panel-layout.css','panel-shell.mjs','restore-view.css','restore-view.mjs',
                         'approved-appearance.css','panel-app.css','panel-app.mjs',
                         'dashboard-controller.mjs','dashboard-view.mjs'):
                responses=[]
                body=b''.join(app({'REQUEST_METHOD':'GET','PATH_INFO':'/assets/'+name},
                    lambda status,headers:responses.append((status,dict(headers)))))
                self.assertEqual(responses[0][0],'200 OK')
                expected='text/css' if name.endswith('.css') else 'text/javascript'
                self.assertEqual(responses[0][1]['Content-Type'],expected+'; charset=utf-8')
                self.assertTrue(body)

    def test_entry_page_is_public_but_contains_no_private_state(self):
        with tempfile.TemporaryDirectory() as d:
            app=Web(d); responses=[]
            body=b''.join(app({'REQUEST_METHOD':'GET','PATH_INFO':'/'},
                lambda status,headers:responses.append((status,dict(headers)))))
            status,headers=responses[0]
            self.assertEqual(status,'200 OK')
            self.assertEqual(headers['Content-Type'],'text/html; charset=utf-8')
            self.assertIn("script-src 'self'",headers['Content-Security-Policy'])
            self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
            self.assertIn(b'/assets/panel-app.mjs',body)
            self.assertNotIn(b'csrf',body)
            self.assertNotIn(b'TrueNASPlexConfig_',body)

    def test_browser_module_served_without_exposing_other_paths(self):
        with tempfile.TemporaryDirectory() as d:
            app=Web(d); responses=[]
            body=b''.join(app({'REQUEST_METHOD':'GET','PATH_INFO':'/assets/panel-client.mjs'},
                lambda status,headers:responses.append((status,dict(headers)))))
            self.assertEqual(responses[0][0],'200 OK')
            self.assertEqual(responses[0][1]['Content-Type'],'text/javascript; charset=utf-8')
            self.assertIn(b'export class PanelClient',body)
            responses=[]
            app({'REQUEST_METHOD':'GET','PATH_INFO':'/assets/../auth.py'},
                lambda status,headers:responses.append(status))
            self.assertEqual(responses[0],'401 Unauthorized')

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
                r,session=request('GET','/api/session',headers=headers)
                self.assertEqual(r.status,200)
                self.assertEqual(session['csrf'],body['csrf'])
                r,operation=request('GET','/api/operation',headers=headers)
                self.assertEqual(r.status,200)
                self.assertEqual(operation['publication']['status'],'NONE')
                archive='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'
                record(d,'.pcc-'+'a'*32+'.tmp',archive)
                r,operation=request('GET','/api/operation',headers=headers)
                self.assertEqual(r.status,200)
                self.assertEqual(operation['publication']['archive'],archive)
                self.assertEqual(operation['publication']['status'],'VERIFICATION_REQUIRED')
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
