"""Persistent opaque sessions: explicit logout, no inactivity expiration.

Web integration must use Secure, HttpOnly, SameSite cookies and CSRF protection.
Only hashes of bearer tokens are stored in the application ixVolume.
"""
import hashlib
import secrets
import sqlite3
from pathlib import Path

class Sessions:
    def __init__(self, state_directory):
        directory=Path(state_directory)
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=directory/'sessions.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions '
                       '(digest TEXT PRIMARY KEY, csrf TEXT NOT NULL)')
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

    def create(self):
        token=secrets.token_urlsafe(48)
        csrf=secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES (?,?)',(self.digest(token),csrf))
        return token,csrf

    def authenticated(self,token):
        digest=self.digest(token)
        if digest is None: return False
        with self.connect() as db:
            return db.execute('SELECT 1 FROM sessions WHERE digest=?',(digest,)).fetchone() is not None

    def check_csrf(self,token,submitted):
        digest=self.digest(token)
        if digest is None or not isinstance(submitted,str): return False
        with self.connect() as db:
            row=db.execute('SELECT csrf FROM sessions WHERE digest=?',(digest,)).fetchone()
        return bool(row and secrets.compare_digest(row[0],submitted))

    def csrf_for(self,token):
        digest=self.digest(token)
        if digest is None: return None
        with self.connect() as db:
            row=db.execute('SELECT csrf FROM sessions WHERE digest=?',(digest,)).fetchone()
        return row[0] if row else None

    def logout(self,token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE digest=?',(self.digest(token),))

    def revoke_all(self):
        """Use after a successful password change; require a fresh login."""
        with self.connect() as db:
            db.execute('DELETE FROM sessions')
