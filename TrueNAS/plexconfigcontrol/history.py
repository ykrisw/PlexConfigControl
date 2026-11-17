"""Panel history is independent from permanent operation log files."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class History:
    def __init__(self, state_directory):
        directory = Path(state_directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'history.sqlite3'
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('PRAGMA secure_delete=ON')
            existing = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
            # Never reuse deleted identities: a stale browser selection must not
            # delete or download a different event added after a history clear.
            migrate = existing is not None and 'AUTOINCREMENT' not in existing[0].upper()
            if migrate:
                db.execute('ALTER TABLE events RENAME TO events_before_identity_migration')
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, '
                       'created TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, '
                       'archive TEXT, log TEXT NOT NULL)')
            if migrate:
                db.execute('INSERT INTO events SELECT * FROM events_before_identity_migration')
                db.execute('DROP TABLE events_before_identity_migration')
        self.path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA secure_delete=ON')
        return db

    def add(self, kind, status, log, archive=None):
        with self.connect() as db:
            cursor = db.execute('INSERT INTO events(created,kind,status,archive,log) '
                                'VALUES (?,?,?,?,?)',
                                (datetime.now(timezone.utc).isoformat(), kind, status, archive, log))
            return cursor.lastrowid

    def list(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                'SELECT id,created,kind,status,archive FROM events ORDER BY id DESC')]

    def detail(self, event_id):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
            return dict(row) if row else None

    def clear(self, ids):
        """Delete only selected panel records; never open the archive/log directory.

        Confirmation and authorization must be enforced by the calling web route.
        secure_delete clears deleted SQLite cells; external filesystem snapshots
        and backups are outside the application's history deletion boundary.
        """
        with self.connect() as db:
            db.executemany('DELETE FROM events WHERE id=?', ((int(i),) for i in ids))
