"""Durable progress reporting. Percent is absent without a known total."""
import sqlite3
import time
from pathlib import Path

STAGES = {'PREPARING','CREATING_SNAPSHOT','CREATING_ARCHIVE','VERIFYING_ARCHIVE',
          'WAITING_FOR_PLEX_STOP','RESTORING','VERIFYING_RESTORE','ROLLING_BACK',
          'REMOVING_SNAPSHOT','COMPLETED','FAILED','CLEANUP_REQUIRED',
          'READING_ARCHIVE','CHECKING_GZIP','HASHING_ARCHIVE','CANCELLED','PUBLISHING_ARCHIVE'}

class Progress:
    def __init__(self,state_directory):
        directory=Path(state_directory)
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=directory/'progress.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS progress (id INTEGER PRIMARY KEY CHECK(id=1), '
                       'operation TEXT, stage TEXT, started REAL, updated REAL, finished REAL, '
                       'done INTEGER, total INTEGER)')
        self.path.chmod(0o600)

    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        return db

    def start(self,operation,now=None):
        if operation not in ('BACKUP','RESTORE'): raise ValueError('Invalid operation')
        now=time.time() if now is None else now
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO progress VALUES(1,?,?,?,?,NULL,0,NULL)',
                       (operation,'PREPARING',now,now))

    def update(self,stage,done=0,total=None,now=None):
        if stage not in STAGES: raise ValueError('Invalid stage')
        if type(done) is not int or done<0: raise ValueError('Invalid byte count')
        if total is not None and (type(total) is not int or total<=0 or done>total):
            raise ValueError('Invalid total')
        now=time.time() if now is None else now
        terminal=stage in ('COMPLETED','FAILED','CLEANUP_REQUIRED','CANCELLED')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM progress WHERE id=1').fetchone()
            if row is None or row['finished'] is not None:
                raise ValueError('No active progress record')
            if stage==row['stage'] and done<row['done']:
                raise ValueError('Progress cannot move backwards within a stage')
            db.execute('UPDATE progress SET stage=?,done=?,total=?,updated=?,finished=? WHERE id=1',
                       (stage,done,total,now,now if terminal else None))

    def fail_closed(self, cleanup_required, now=None):
        """Override a premature terminal success when final reporting fails.

        Caller holds the operation lock. Failure can never become success here,
        and already-required cleanup cannot be downgraded. Preserve the original
        finish time so elapsed time does not grow while awaiting investigation.
        """
        if type(cleanup_required) is not bool:
            raise ValueError('Explicit cleanup state required')
        now=time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM progress WHERE id=1').fetchone()
            if row is None:
                return
            stage='CLEANUP_REQUIRED' if cleanup_required or row['stage']=='CLEANUP_REQUIRED' else 'FAILED'
            finished=row['finished'] if row['finished'] is not None else now
            db.execute('UPDATE progress SET stage=?,done=0,total=NULL,updated=?,finished=? WHERE id=1',
                       (stage,now,finished))

    def resolve_cleanup(self):
        """Keep the failed operation's original end time; never report success.

        Caller holds the operation lock and has verified publication recovery.
        Retrying after the durable state checkpoint is harmless.
        """
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM progress WHERE id=1').fetchone()
            if row is None:
                return
            if (row['operation'] != 'BACKUP' or row['finished'] is None
                    or row['stage'] not in ('FAILED', 'CLEANUP_REQUIRED')):
                raise ValueError('Unexpected progress during publication recovery')
            db.execute("UPDATE progress SET stage='FAILED' WHERE id=1")

    def read(self,now=None):
        now=time.time() if now is None else now
        with self.connect() as db:
            row=db.execute('SELECT * FROM progress WHERE id=1').fetchone()
        if row is None: return None
        result=dict(row); result.pop('id')
        result['elapsed_seconds']=max(0,(row['finished'] if row['finished'] is not None else now)-row['started'])
        result['stage_percent']=round(100*row['done']/row['total'],1) if row['total'] else None
        result['active']=row['finished'] is None
        return result
