import io
import json
import os
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from cryptography import x509
from plexconfigcontrol.auth import Account
from plexconfigcontrol.installation import initialize_from_verifier, password_verifier
from plexconfigcontrol.runtime import Configuration, ReadOnlyTrueNAS, prepare
from plexconfigcontrol.tls import ensure_tls


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.verifier=password_verifier('initial-test-password')

    def request(self,app,path,method='GET',body=None,cookie=None,csrf=None):
        payload=json.dumps(body).encode() if body is not None else b''
        headers=[]
        env={'REQUEST_METHOD':method,'PATH_INFO':path,'wsgi.input':io.BytesIO(payload),
             'CONTENT_LENGTH':str(len(payload)),'CONTENT_TYPE':'application/json'}
        if path=='/api/login': env['HTTP_X_PCC_REQUEST']='1'
        if cookie: env['HTTP_COOKIE']=cookie
        if csrf: env['HTTP_X_CSRF_TOKEN']=csrf
        data=b''.join(app(env,lambda status,values:headers.append((status,dict(values)))))
        return *headers[0],data

    def test_restart_preserves_password_sessions_settings_and_tls(self):
        with tempfile.TemporaryDirectory() as d:
            config=Configuration(Path(d),'192.168.1.120')
            app,cert,key=prepare(config,self.verifier)
            first_cert=cert.read_bytes();first_key=key.read_bytes()
            code,headers,data=self.request(app,'/api/login','POST',{'password':'initial-test-password'})
            self.assertEqual(code,'200 OK')
            cookie=headers['Set-Cookie'].split(';')[0];csrf=json.loads(data)['csrf']
            self.request(app,'/api/settings','POST',{'theme':'Dark'},cookie,csrf)
            app.web.account.change_password('initial-test-password','changed-password')
            app,cert,key=prepare(config,'ignored existing install')
            code,_,data=self.request(app,'/api/settings',cookie=cookie)
            self.assertEqual(code,'200 OK');self.assertEqual(json.loads(data)['theme'],'Dark')
            self.assertFalse(app.web.account.login('initial-test-password')['authenticated'])
            self.assertTrue(app.web.account.login('changed-password')['authenticated'])
            self.assertEqual(cert.read_bytes(),first_cert);self.assertEqual(key.read_bytes(),first_key)
            self.assertEqual(key.stat().st_mode & 0o077,0)

    def test_test_runtime_denies_host_operations_and_does_not_touch_archives(self):
        with tempfile.TemporaryDirectory() as d:
            archives=Path(d)/'archives';archives.mkdir()
            marker=archives/'existing-data';marker.write_text('keep')
            app,_,_=prepare(Configuration(Path(d)/'state','localhost',archives=archives),self.verifier)
            for path in ('/api/backup/start','/api/restore/execute','/api/archives/delete','/api/snapshots/delete'):
                code,_,_=self.request(app,path,'POST',{})
                self.assertEqual(code,'403 Forbidden')
            self.assertEqual(marker.read_text(),'keep');self.assertEqual(list(archives.iterdir()),[marker])
            self.assertEqual(self.request(app,'/healthz')[0],'200 OK')
            self.assertEqual(self.request(app,'/api/history')[0],'401 Unauthorized')
            token,_=app.web.sessions.create()
            code,_,data=self.request(app,'/api/capabilities',cookie='pcc_session='+token)
            self.assertEqual(code,'200 OK');self.assertFalse(json.loads(data)['archive_delete'])
            self.assertEqual(self.request(app,'/api/backup/plan',cookie='pcc_session='+token)[0],'200 OK')

    def test_missing_or_invalid_bootstrap_never_creates_usable_account(self):
        with tempfile.TemporaryDirectory() as d:
            config=Configuration(Path(d),'localhost')
            for value in (None,'plaintext','pbkdf2-sha256$1$'+'a'*64+'$'+'b'*64):
                with self.assertRaises(ValueError): prepare(config,value)
            with Account(d).connect() as db:
                self.assertIsNone(db.execute('SELECT id FROM account').fetchone())

    def test_verifier_is_salted_and_initialization_never_overwrites(self):
        first=password_verifier('same');second=password_verifier('same')
        self.assertNotEqual(first,second);self.assertNotIn('same',first)
        with tempfile.TemporaryDirectory() as d:
            account=Account(d);initialize_from_verifier(account,first)
            self.assertTrue(account.login('same')['authenticated'])
            import sqlite3
            with self.assertRaises(sqlite3.IntegrityError): initialize_from_verifier(account,second)

    def test_status_adapter_cannot_stop_apps_or_access_snapshots(self):
        client=Mock();adapter=ReadOnlyTrueNAS(client)
        for method in ('app.stop','app.start','pool.snapshot.query','pool.snapshot.create',
                       'pool.snapshot.delete','pool.snapshot.rollback'):
            with self.assertRaises(PermissionError): adapter.call(method,'anything')
        client.call.assert_not_called()
        adapter.call('app.query',[['name','=','other-app']])
        client.call.assert_called_once_with('app.query',[['name','=','plex']],{'select':['name','state']})

    def test_configuration_rejects_plain_password_and_partial_connection(self):
        for changes in ({'PCC_INITIAL_PASSWORD':'secret'}, {'PCC_PORT':'443'},
                        {'PCC_STATE_DIRECTORY':'relative'}, {'PCC_API_USERNAME':'user'}):
            with self.assertRaises(ValueError):
                Configuration.from_environment({'PCC_PUBLIC_HOST':'localhost',**changes})

    def test_tls_is_trusted_by_local_probe_and_host_changes_require_explicit_action(self):
        with tempfile.TemporaryDirectory() as d:
            cert,key=ensure_tls(d,'192.168.1.120')
            context=ssl.create_default_context(cafile=str(cert))
            self.assertTrue(context.check_hostname)
            parsed=x509.load_pem_x509_certificate(cert.read_bytes())
            names=parsed.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            self.assertIn(x509.DNSName('localhost'),names)
            with self.assertRaises(ValueError): ensure_tls(d,'192.168.1.121')
            original=cert.read_bytes();key.unlink()
            with self.assertRaises(OSError): ensure_tls(d,'192.168.1.120')
            self.assertEqual(cert.read_bytes(),original)
