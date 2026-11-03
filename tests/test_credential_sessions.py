"""Credential-bound sessions fail closed even if row cleanup fails."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from plexconfigcontrol.auth import Account
from plexconfigcontrol.sessions import Sessions,SessionChanged
from plexconfigcontrol.web import Web


class CredentialSessionTests(unittest.TestCase):
    def request(self,app,path,body=None,cookie=None,csrf=None):
        from test_runtime import RuntimeTests
        return RuntimeTests().request(app,path,'POST' if body is not None else 'GET',body,cookie,csrf)

    def test_password_change_invalidates_stored_sessions_without_deleting_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            account=Account(directory);account.initialize('old-password');sessions=Sessions(directory,account)
            token,csrf=sessions.create();self.assertTrue(sessions.authenticated(token))
            self.assertTrue(account.change_password('old-password','new-password'))
            with sessions.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0],1)
            self.assertFalse(sessions.authenticated(token));self.assertFalse(sessions.check_csrf(token,csrf))
            self.assertIsNone(sessions.csrf_for(token))
            fresh,_=sessions.create();self.assertTrue(Sessions(directory).authenticated(fresh))

    def test_web_change_remains_secure_when_session_row_deletion_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Web(directory);app.account.initialize('old-password')
            first,csrf=app.sessions.create();second,_=app.sessions.create()
            with patch.object(app.sessions,'revoke_all',side_effect=OSError('private cleanup secret')):
                status,_,body=self.request(app,'/api/account/password',
                    {'current_password':'old-password','new_password':'new-password','confirm_new_password':'new-password'},
                    'pcc_session='+first,csrf)
            self.assertEqual(status,'200 OK');result=json.loads(body)
            self.assertTrue(result['changed']);self.assertTrue(result['session_cleanup_pending'])
            self.assertNotIn('secret',body.decode())
            self.assertFalse(app.sessions.authenticated(first));self.assertFalse(app.sessions.authenticated(second))
            self.assertEqual(self.request(app,'/api/session',cookie='pcc_session='+second)[0],'401 Unauthorized')
            self.assertEqual(self.request(app,'/api/login',{'password':'new-password'})[0],'200 OK')

    def test_history_failure_does_not_keep_old_session_or_report_history_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Web(directory);app.account.initialize('old-password');token,csrf=app.sessions.create()
            with patch.object(app.history,'add',side_effect=OSError('private History path')):
                status,_,body=self.request(app,'/api/account/password',
                    {'current_password':'old-password','new_password':'new-password','confirm_new_password':'new-password'},
                    'pcc_session='+token,csrf)
            self.assertEqual(status,'200 OK');self.assertFalse(json.loads(body)['history_recorded'])
            self.assertNotIn('private',body.decode());self.assertFalse(app.sessions.authenticated(token))
            self.assertTrue(app.account.login('new-password')['authenticated'])

    def test_upgrade_invalidates_unbound_legacy_sessions_once_then_restarts_preserve_new_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            account=Account(directory);account.initialize('password')
            token='legacy-token-'+'a'*48
            with sqlite3.connect(Path(directory)/'sessions.sqlite3') as db:
                db.execute('CREATE TABLE sessions(digest TEXT PRIMARY KEY,csrf TEXT NOT NULL)')
                db.execute('INSERT INTO sessions VALUES (?,?)',(Sessions.digest(token),'legacy-csrf'))
            sessions=Sessions(directory,account);self.assertFalse(sessions.authenticated(token))
            fresh,csrf=sessions.create();reopened=Sessions(directory,Account(directory))
            self.assertTrue(reopened.authenticated(fresh));self.assertTrue(reopened.check_csrf(fresh,csrf))
            self.assertFalse(reopened.authenticated(token))

    def test_session_cannot_be_created_from_password_verified_before_a_change(self):
        with tempfile.TemporaryDirectory() as directory:
            account=Account(directory);account.initialize('old-password');sessions=Sessions(directory,account)
            verified=account.login('old-password');account.change_password('old-password','new-password')
            with self.assertRaises(SessionChanged):sessions.create(expected_stamp=verified['credential_stamp'])
            with sessions.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0],0)

    def test_password_change_during_session_insert_cannot_authorize_the_old_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            account=Account(directory);account.initialize('old-password');sessions=Sessions(directory,account)
            stamp=account.credential_stamp();connect=sessions.connect;changed=[]
            @contextmanager
            def concurrent_change():
                with connect() as db:yield db
                if not changed:
                    changed.append(True);account.change_password('old-password','new-password')
            with patch.object(sessions,'connect',side_effect=concurrent_change):
                with self.assertRaises(SessionChanged):sessions.create(expected_stamp=stamp)
            with sessions.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0],0)

    def test_concurrent_password_change_cannot_overwrite_a_newer_password_with_stale_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            account=Account(directory);account.initialize('old-password');derive=account.derive;changed=[]
            def concurrent(password,*args):
                if password=='first-new' and not changed:
                    changed.append(True);self.assertTrue(account.change_password('old-password','second-new'))
                return derive(password,*args)
            with patch.object(account,'derive',side_effect=concurrent):
                self.assertFalse(account.change_password('old-password','first-new'))
            self.assertTrue(account.login('second-new')['authenticated'])
            self.assertFalse(account.login('first-new')['authenticated'])

    def test_login_racing_password_change_returns_conflict_without_a_session_cookie(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Web(directory);app.account.initialize('old-password');create=app.sessions.create
            def concurrent(*args,**kwargs):
                app.account.change_password('old-password','new-password')
                return create(*args,**kwargs)
            with patch.object(app.sessions,'create',side_effect=concurrent):
                status,headers,_=self.request(app,'/api/login',{'password':'old-password'})
            self.assertEqual(status,'409 Conflict');self.assertNotIn('Set-Cookie',headers)
            status,_,body=self.request(app,'/api/login',{'password':'new-password'})
            self.assertEqual(status,'200 OK');self.assertNotIn('credential_stamp',body.decode())
            self.assertNotIn(app.account.credential_stamp(),body.decode())
