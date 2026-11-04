"""Persist observed archive arrivals independently of deletable web history.

Observation is not validation or a filesystem audit. Copy source/time is unknown;
files which appear/disappear between scans cannot be reconstructed. No hashes or
archive extraction on scans, no ACL changes and no app/Plex/snapshot operations.
"""
import hashlib
import os
import re
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .archive_store import ArchiveStore
from .locking import operation_lock, OperationBusy
from .operations import Phase
from .publication_intent import pending


class ArchiveDiscovery:
    def __init__(self, directory, state_directory, history, *, permanent_logs=True):
        self.directory = Path(directory)
        self.state = Path(state_directory)
        self.history = history
        self.permanent_logs = permanent_logs
        self.scope = hashlib.sha256(os.fsencode(os.path.abspath(directory))).hexdigest()
        self.archives = ArchiveStore(directory, state_directory)
        with history.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS archive_seen ('
                       'scope TEXT, name TEXT, device TEXT, inode TEXT, '
                       'PRIMARY KEY(scope,name))')
            db.execute('CREATE TABLE IF NOT EXISTS archive_log_outbox ('
                       'scope TEXT, name TEXT PRIMARY KEY, body TEXT NOT NULL)')

    def remember_created(self, name):
        """Backup coordinator calls under its operation lock after publication.

        Persist origin knowledge even if the user later clears BACKUP history.
        Never use History entries as an archive allowlist.
        """
        item = next((item for item in self.archives.list() if item.name == name), None)
        if item is None:
            raise FileNotFoundError('Published archive is unavailable')
        with self.history.connect() as db:
            db.execute('INSERT OR REPLACE INTO archive_seen VALUES (?,?,?,?)',
                       (self.scope, item.name, str(item.device), str(item.inode)))

    def scan(self):
        try:
            with operation_lock(self.state):
                with self.archives.state.transaction() as operation:
                    blocked = operation.phase in (Phase.RUNNING, Phase.VALIDATING, Phase.RECOVERY_REQUIRED)
                rows = self.archives.list()
                if not blocked and not pending(self.state):
                    self._observe(rows)
                    if self.permanent_logs:
                        self._flush_logs()
                return rows
        except OperationBusy:
            # Listing is still useful while another operation owns the lock.
            # Its partially published output must not be called an import.
            return self.archives.list()

    def _observe(self, rows):
        with self.history.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            seen = {name: (device, inode) for name, device, inode in db.execute(
                'SELECT name,device,inode FROM archive_seen WHERE scope=?', (self.scope,))}
            current = {item.name for item in rows}
            for item in rows:
                identity = (str(item.device), str(item.inode))
                if seen.get(item.name) == identity:
                    continue
                now = datetime.now(timezone.utc)
                log_name = now.astimezone(ZoneInfo('Europe/London')).strftime(
                    'ArchiveImport_%Y.%m.%d_%H.%M.%S_')+secrets.token_hex(8)+'.log'
                body = ('['+now.isoformat()+'] Archive detected in backup folder: '+item.name+'\n'
                        'Size at detection: '+str(item.size)+' bytes.\n'
                        'Detected by directory scan; original copy time and source are unknown.\n'
                        'Not recorded as app-created in this installation. This may be a returned copy, '
                        'an external import or a file found on the first scan.\n'
                        'NOT VALIDATED. Complete the copy and validate this archive before Restore.\n'
                        'Permanent log destination: Logs/'+log_name+'\n')
                db.execute('INSERT INTO events(created,kind,status,archive,log) VALUES (?,?,?,?,?)',
                           (now.isoformat(), 'ARCHIVE_DETECTED', 'INFO', item.name, body))
                db.execute('INSERT OR REPLACE INTO archive_seen VALUES (?,?,?,?)',
                           (self.scope, item.name, *identity))
                db.execute('INSERT INTO archive_log_outbox VALUES (?,?,?)',
                           (self.scope, log_name, body))
            for name in seen.keys()-current:
                db.execute('DELETE FROM archive_seen WHERE scope=? AND name=?', (self.scope, name))

    def _flush_logs(self):
        """Create-only permanent records, with a durable private retry outbox.

        Crash after complete file creation is reconciled by byte comparison.
        Conflicting/incomplete files are never edited, deleted or overwritten.
        Manual deletion after acknowledgement does not recreate a completed log.
        """
        with self.history.connect() as db:
            queued = db.execute('SELECT name,body FROM archive_log_outbox WHERE scope=? '
                                'ORDER BY name LIMIT 100', (self.scope,)).fetchall()
        if not queued:
            return
        try:
            parent = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                logs = os.open('Logs', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            finally:
                os.close(parent)
        except OSError:
            return  # Keep outbox; status explicitly reports pending files.
        try:
            for name, body in queued:
                # The private DB is not an arbitrary-path command interface.
                if not re.fullmatch(r'ArchiveImport_\d{4}\.\d{2}\.\d{2}_\d{2}\.\d{2}\.\d{2}_[0-9a-f]{16}\.log', name):
                    continue
                payload = body.encode('utf-8')
                try:
                    try:
                        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o666, dir_fd=logs)
                    except FileExistsError:
                        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=logs)
                        with os.fdopen(fd, 'rb') as source:
                            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                                continue
                            if source.read(len(payload)+1) != payload:
                                continue
                            os.fsync(source.fileno())
                    else:
                        with os.fdopen(fd, 'wb') as output:
                            output.write(payload)
                            output.flush()
                            os.fsync(output.fileno())
                    os.fsync(logs)
                    with self.history.connect() as db:
                        db.execute('DELETE FROM archive_log_outbox WHERE scope=? AND name=?', (self.scope, name))
                except OSError:
                    continue
        finally:
            os.close(logs)

    def status(self):
        with self.history.connect() as db:
            count = db.execute('SELECT COUNT(*) FROM archive_log_outbox WHERE scope=?', (self.scope,)).fetchone()[0]
        return {'pending_logs': count, 'permanent_logs_enabled': self.permanent_logs}
