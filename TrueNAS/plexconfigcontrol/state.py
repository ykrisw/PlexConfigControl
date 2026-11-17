"""Durable single-operation state, stored under the application's ixVolume."""
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .operations import Operation, Phase


class StateStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.directory / 'operations.sqlite3'
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS operation '
                       '(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO operation VALUES (1, ?)',
                       (json.dumps(asdict(Operation())),))
        self.path.chmod(0o600)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute('PRAGMA synchronous=FULL')
        return db

    @contextmanager
    def transaction(self):
        """Serialize state transitions. Never perform network I/O inside this lock.

        Record snapshot intent in a committed transaction BEFORE calling TrueNAS.
        On timeout retain intent and reconcile the exact snapshot; never retry
        creation using another name while the earlier result remains uncertain.
        """
        db = self._connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            payload = json.loads(db.execute(
                'SELECT payload FROM operation WHERE id=1').fetchone()[0])
            payload['phase'] = Phase(payload['phase'])
            operation = Operation(**payload)
            yield operation
            db.execute('UPDATE operation SET payload=? WHERE id=1',
                       (json.dumps(asdict(operation)),))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
