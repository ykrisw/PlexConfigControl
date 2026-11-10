"""Persistent password-only account and escalating login lockout."""
import hashlib
import hmac
import secrets
import sqlite3
import time
from pathlib import Path

STAGES = ((5, 300), (5, 900), (2, 900), (1, 900))
ITERATIONS = 600_000

class Account:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'account.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS account '
                       '(id INTEGER PRIMARY KEY CHECK(id=1), salt BLOB NOT NULL, '
                       'digest BLOB NOT NULL, iterations INTEGER NOT NULL, '
                       'stage INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0, '
                       'blocked_until REAL NOT NULL DEFAULT 0)')
        self.path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA secure_delete=ON')
        return db

    @staticmethod
    def derive(password, salt, iterations):
        return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)

    @staticmethod
    def _stamp(salt, digest, iterations):
        return hashlib.sha256(salt+digest+str(iterations).encode('ascii')).hexdigest()

    def credential_stamp(self):
        """Private session binding; never return this value through the API."""
        with self.connect() as db:
            row=db.execute('SELECT salt,digest,iterations FROM account WHERE id=1').fetchone()
        return self._stamp(*row) if row else 'uninitialized'

    def initialize(self, password):
        if not password:
            raise ValueError('Password is required')
        salt = secrets.token_bytes(32)
        digest = self.derive(password, salt, ITERATIONS)
        with self.connect() as db:
            # Existing credentials must never be overwritten at container restart.
            db.execute('INSERT INTO account(id,salt,digest,iterations) VALUES(1,?,?,?)',
                       (salt, digest, ITERATIONS))

    def login(self, password, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT salt,digest,iterations,stage,failures,blocked_until '
                             'FROM account WHERE id=1').fetchone()
            if row is None:
                raise RuntimeError('Account is not initialized')
            salt, digest, iterations, stage, failures, blocked = row
            if blocked > now:
                return {'authenticated': False, 'blocked_until': blocked, 'remaining': 0}
            if iterations == 0 and salt == b'':
                # Catalog bootstrap accounts start with a bcrypt verifier.
                # Reject long inputs explicitly for bcrypt versions that truncate them.
                import bcrypt
                encoded = password.encode('utf-8')
                valid = len(encoded) <= 72 and bcrypt.checkpw(encoded, digest)
            else:
                valid = hmac.compare_digest(self.derive(password, salt, iterations), digest)
            if valid:
                db.execute('UPDATE account SET stage=0,failures=0,blocked_until=0 WHERE id=1')
                return {'authenticated': True, 'blocked_until': 0, 'remaining': 5,
                        'credential_stamp': self._stamp(salt,digest,iterations)}
            limit, delay = STAGES[stage]
            failures += 1
            remaining = limit - failures
            blocked = 0
            if failures >= limit:
                blocked = now + delay
                stage = min(stage + 1, len(STAGES)-1)
                failures = 0
            db.execute('UPDATE account SET stage=?,failures=?,blocked_until=? WHERE id=1',
                       (stage, failures, blocked))
            return {'authenticated': False, 'blocked_until': blocked, 'remaining': max(0,remaining)}

    def change_password(self, current, new):
        if not new:
            raise ValueError('New password is required')
        # Current-password checks use the same persistent lockout as login.
        verified=self.login(current)
        if not verified['authenticated']:
            return False
        salt = secrets.token_bytes(32)
        digest = self.derive(new, salt, ITERATIONS)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT salt,digest,iterations FROM account WHERE id=1').fetchone()
            if row is None or not hmac.compare_digest(self._stamp(*row),verified['credential_stamp']):
                return False
            db.execute('UPDATE account SET salt=?,digest=?,iterations=? WHERE id=1',
                       (salt, digest, ITERATIONS))
        return True
