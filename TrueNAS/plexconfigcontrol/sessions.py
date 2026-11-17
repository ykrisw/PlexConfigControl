"""Persistent opaque sessions: explicit logout, no inactivity expiration.

Web integration must use Secure, HttpOnly, SameSite cookies and CSRF protection.
Only hashes of bearer tokens are stored in the application ixVolume.
"""
import hashlib
import secrets
import sqlite3
from pathlib import Path
from .auth import Account

class SessionChanged(RuntimeError):
    pass


class Sessions:
    def __init__(self, state_directory, account=None):
        directory=Path(state_directory)
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.account=account if account is not None else Account(directory)
        self.path=directory/'sessions.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions '
                       '(digest TEXT PRIMARY KEY, csrf TEXT NOT NULL, credential_stamp TEXT)')
            columns={row[1] for row in db.execute('PRAGMA table_info(sessions)')}
            if 'credential_stamp' not in columns:
                db.execute('ALTER TABLE sessions ADD COLUMN credential_stamp TEXT')
            # Old unbound sessions cannot be proven to match current credentials.
            # Upgrade invalidates them once; ordinary restarts retain bound rows.
            db.execute('DELETE FROM sessions WHERE credential_stamp IS NULL')
        self.path.chmod(0o600)

    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA secure_delete=ON')
        return db

    @staticmethod
    def digest(token):
        if not isinstance(token,str) or not 20 <= len(token) <= 256:
            return None
        return hashlib.sha256(token.encode()).hexdigest()

    def create(self, expected_stamp=None):
        current=self.account.credential_stamp()
        stamp=current if expected_stamp is None else expected_stamp
        if not isinstance(stamp,str) or not secrets.compare_digest(stamp,current):
            raise SessionChanged('Credentials changed during sign-in')
        token=secrets.token_urlsafe(48)
        csrf=secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('INSERT INTO sessions(digest,csrf,credential_stamp) VALUES (?,?,?)',
                       (self.digest(token),csrf,stamp))
        if not secrets.compare_digest(stamp,self.account.credential_stamp()):
            try: self.logout(token)
            except Exception: pass
            raise SessionChanged('Credentials changed during sign-in')
        return token,csrf

    def _row(self,token):
        digest=self.digest(token)
        if digest is None:return None
        with self.connect() as db:
            row=db.execute('SELECT csrf,credential_stamp FROM sessions WHERE digest=?',(digest,)).fetchone()
        if (row is None or not isinstance(row[1],str)
                or not secrets.compare_digest(row[1],self.account.credential_stamp())):
            return None
        return row

    def authenticated(self,token):
        return self._row(token) is not None

    def check_csrf(self,token,submitted):
        if not isinstance(submitted,str):return False
        row=self._row(token)
        return bool(row and secrets.compare_digest(row[0],submitted))

    def csrf_for(self,token):
        row=self._row(token)
        return row[0] if row else None

    def logout(self,token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE digest=?',(self.digest(token),))

    def revoke_all(self):
        """Use after a successful password change; require a fresh login."""
        with self.connect() as db:
            db.execute('DELETE FROM sessions')
