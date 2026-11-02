"""Validated preferences stored exclusively in application state storage."""
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULTS = {'theme': 'System', 'language': 'en', 'timezone': 'Europe/London'}

class Settings:
    def __init__(self, state_directory):
        directory=Path(state_directory)
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=directory/'settings.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS preferences '
                       '(name TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.executemany('INSERT OR IGNORE INTO preferences VALUES (?,?)',DEFAULTS.items())
        self.path.chmod(0o600)

    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def read(self):
        with self.connect() as db:
            return dict(db.execute('SELECT name,value FROM preferences'))

    def update(self, **changes):
        # Persist the selected UI language independently of filenames and machine states.
        for name,value in changes.items():
            if name not in DEFAULTS:
                raise ValueError('Unknown preference')
            if not isinstance(value,str):
                raise ValueError('Preference must be text')
            if name=='theme' and value not in ('System','Light','Dark'):
                raise ValueError('Unsupported theme')
            if name=='language' and value not in ('en','pl'):
                raise ValueError('Unsupported language')
            if name=='timezone':
                try: ZoneInfo(value)
                except (ZoneInfoNotFoundError, ValueError) as error:
                    raise ValueError('Unknown timezone') from error
        with self.connect() as db:
            db.executemany('UPDATE preferences SET value=? WHERE name=?',
                           ((value,name) for name,value in changes.items()))
        return self.read()
