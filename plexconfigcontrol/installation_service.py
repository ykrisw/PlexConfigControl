"""Authenticated installer adapter; deliberately not registered as a WWW route.

A trusted deployment owns the API client/state and provides HTTPS/origin/body
limits in its transport. This service grants no generic host command capability.
"""
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import RLock

from .installation_flow import InstallationStorageFlow
from .locking import operation_lock, OperationBusy
from .sessions import Sessions
from .state import StateStore
from .operations import Phase
from .publication_intent import pending as publication_pending


class InstallationDenied(RuntimeError):
    pass


def _public_errors(method):
    @wraps(method)
    def call(*args,**kwargs):
        try:return method(*args,**kwargs)
        except InstallationDenied:raise
        except OperationBusy:raise InstallationDenied('INSTALLATION_BUSY') from None
        except Exception:raise InstallationDenied('INSTALLATION_UNAVAILABLE') from None
    return call


class InstallationService:
    def __init__(self, api, sessions, state_directory, language='en'):
        self.state=Path(state_directory)
        if not self.state.is_dir() or self.state.is_symlink():raise ValueError('Private installer state is required')
        if not isinstance(sessions,Sessions) or sessions.path.parent.resolve()!=self.state.resolve():
            raise ValueError('Installer sessions must belong to the private installation state')
        self.sessions=sessions
        self.language='pl' if language=='pl' else 'en'
        self._flow=InstallationStorageFlow(api,self.language,state_directory=self.state)
        self._owner=None
        self._lock=RLock()
        self.path=self.state/'installation.sqlite3'
        if self.path.is_symlink():raise InstallationDenied('INSTALLATION_REVIEW_REQUIRED')
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS installation '
                       '(id INTEGER PRIMARY KEY CHECK(id=1), revision TEXT NOT NULL, '
                       'owner TEXT NOT NULL, status TEXT NOT NULL, receipt TEXT)')
        self.path.chmod(0o600)

    @contextmanager
    def _db(self):
        db=sqlite3.connect(self.path,timeout=5)
        try:
            db.execute('PRAGMA synchronous=FULL')
            yield db
            db.commit()
        except BaseException:
            db.rollback();raise
        finally:db.close()

    def _authenticated(self,token,csrf=None,*,writing=False):
        if not self.sessions.authenticated(token):raise InstallationDenied('SIGN_IN_REQUIRED')
        if writing and not self.sessions.check_csrf(token,csrf):raise InstallationDenied('CSRF_REQUIRED')
        return self.sessions.digest(token)

    def _record(self):
        with self._db() as db:
            return db.execute('SELECT revision,owner,status,receipt FROM installation WHERE id=1').fetchone()

    def _review(self):
        model=self._flow.view()
        model.update(phase='REVIEW_REQUIRED',can_create=False,revision=None,
                     error={'code':'INSTALLATION_REVIEW_REQUIRED','message':
                            'Stan konfiguracji wymaga sprawdzenia. Nie ponawiaj tworzenia folderu.' if self.language=='pl' else
                            'Installation state requires review. Do not repeat folder creation.'})
        return model

    @staticmethod
    def _receipt(record):
        model=json.loads(record[3])
        allowed=('COMPLETE',) if record[2]=='COMPLETE' else ('RENAME_REQUIRED','MANUAL_REQUIRED')
        if not isinstance(model,dict) or model.get('phase') not in allowed or model.get('can_create') is not False or model.get('revision') is not None:
            raise ValueError('Invalid receipt')
        return model

    def _blocked(self,record):
        if record:
            if record[2]!='NO_WRITE':return True
            try:self._receipt(record)
            except (ValueError,TypeError):return True
            return False
        return os.path.lexists(self.state/'output-naming.json')

    def _safe_to_setup(self):
        if publication_pending(self.state):raise InstallationDenied('INSTALLATION_REVIEW_REQUIRED')
        path=self.state/'operations.sqlite3'
        if path.is_symlink():raise InstallationDenied('INSTALLATION_REVIEW_REQUIRED')
        if path.exists():
            with StateStore(self.state).transaction() as operation:
                if operation.phase!=Phase.IDLE or operation.kind is not None or operation.snapshot_id or operation.outcome:
                    raise InstallationDenied('INSTALLATION_REVIEW_REQUIRED')

    @_public_errors
    def status(self,token):
        """Read-only receipt lookup; no discovery, mkdir or replay after restart."""
        self._authenticated(token)
        with self._lock:
            record=self._record()
            if record and (record[2]=='COMPLETE' or (record[2]=='NO_WRITE' and self._owner is None)):
                try:
                    model=self._receipt(record)
                    model['can_create']=False;model['revision']=None
                    return model
                except (ValueError,TypeError,AttributeError):return self._review()
            if self._blocked(record):return self._review()
            model=self._flow.view()
            # A second session cannot read/use another session's checked nonce.
            if self._owner and not secrets.compare_digest(self._owner,self.sessions.digest(token)):
                model.update(phase='UNVERIFIED',can_create=False,revision=None,storage=None,preview=None)
            return model

    @_public_errors
    def check(self,token,csrf,payload):
        owner=self._authenticated(token,csrf,writing=True)
        if (not isinstance(payload,dict) or 'parent' not in payload
                or set(payload)-{'parent','manual_source','folder_name','archive_prefix'}):
            raise InstallationDenied('INVALID_INSTALLATION_INPUT')
        for key,value in payload.items():
            if value is None and key!='parent':continue
            if not isinstance(value,str) or len(value)>4096:raise InstallationDenied('INVALID_INSTALLATION_INPUT')
        with self._lock,operation_lock(self.state):
            if self._blocked(self._record()):raise InstallationDenied('INSTALLATION_REVIEW_REQUIRED')
            self._safe_to_setup()
            if (self._owner and self._owner!=owner and self._flow.view()['phase']=='READY'):
                raise InstallationDenied('INSTALLATION_OWNED_BY_ANOTHER_SESSION')
            self._owner=owner
            return self._flow.check(**payload)

    @_public_errors
    def create(self,token,csrf,payload):
        owner=self._authenticated(token,csrf,writing=True)
        if (not isinstance(payload,dict) or set(payload)!={'revision','confirmed'} or payload['confirmed'] is not True
                or not isinstance(payload['revision'],str) or not re.fullmatch(r'[a-f0-9]{32}',payload['revision'])):
            raise InstallationDenied('EXACT_CONFIRMATION_REQUIRED')
        revision=payload['revision']
        with self._lock,operation_lock(self.state):
            record=self._record()
            if record and record[2]=='COMPLETE' and record[:2]==(revision,owner):
                return self.status(token)  # receipt only; never recreate the folder
            if self._blocked(record):raise InstallationDenied('INSTALLATION_REVIEW_REQUIRED')
            self._safe_to_setup()
            current=self._flow.view()
            if self._owner!=owner or current['phase']!='READY' or current['revision']!=revision:
                raise InstallationDenied('INSTALLATION_PLAN_CHANGED')
            # The durable STARTED record commits before any directory creation.
            # A crash/lost receipt never authorizes restarting the write.
            with self._db() as db:
                db.execute('INSERT INTO installation VALUES(1,?,?,?,NULL) '
                           'ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,owner=excluded.owner,status=excluded.status,receipt=NULL',
                           (revision,owner,'STARTED'))
            try:
                result=self._flow.create(revision,confirmed=True)
                status='COMPLETE' if result['phase']=='COMPLETE' else 'NO_WRITE' if result['phase'] in ('RENAME_REQUIRED','MANUAL_REQUIRED') else 'REVIEW_REQUIRED'
                with self._db() as db:
                    db.execute('UPDATE installation SET status=?,receipt=? WHERE id=1 AND revision=? AND owner=?',
                               (status,json.dumps(result),revision,owner))
                return result
            except Exception:
                # Keep STARTED if receipt persistence fails. Never erase evidence
                # or delete a folder which may already contain external data.
                raise InstallationDenied('INSTALLATION_OUTCOME_UNCONFIRMED') from None
