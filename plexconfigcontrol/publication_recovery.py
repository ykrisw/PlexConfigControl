"""Confirmed recovery of a fully published archive, without host operations.

This coordinator intentionally does not promote partial files, remove leftover
staging files, retire older archives or recover snapshot state. Those cases stay
blocked. The restricted test web runtime does not expose this mutation.
"""
import hashlib
import json
import os
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import publication_intent as intent
from .archive_discovery import ArchiveDiscovery
from .archive_store import file_identity
from .archives import validate_archive
from .eventlog import EventLog
from .locking import operation_lock
from .operations import OperationDenied, Phase


class PublicationRecovery:
    def __init__(self, store, history, progress, state_directory, destination):
        self.store, self.history, self.progress = store, history, progress
        self.state, self.destination = Path(state_directory), Path(destination)

    def _record(self):
        replacement = os.path.lexists(self.state / intent.REPLACEMENT_MARKER)
        ordinary = os.path.lexists(self.state / intent.MARKER)
        if ordinary == replacement:
            raise OperationDenied('Exactly one readable publication record is required')
        item = intent.read_replacement(self.state) if replacement else intent.read(self.state)
        if not item['sha256']:
            raise OperationDenied('Legacy record has no verified digest; manual review required')
        return item, replacement

    def _eligible(self):
        with os.scandir(self.state) as entries:
            if any(entry.name.startswith('backup-') for entry in entries):
                raise OperationDenied('Private backup workspace cleanup requires verification')
        with self.store.transaction() as operation:
            if (operation.kind != 'BACKUP' or operation.snapshot_id
                    or operation.phase not in (Phase.RECOVERY_REQUIRED, Phase.FAILED)):
                raise OperationDenied('Backup recovery with no outstanding snapshot is required')

    @staticmethod
    def _unchanged(parent, fd, item, identity):
        current = os.stat(item['archive'], dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(current.st_mode) or file_identity(current) != identity
                or file_identity(os.fstat(fd)) != identity):
            raise OperationDenied('Published archive changed; verify again')
        # Even a symlink or directory at the staging name must block recovery.
        try:
            os.stat(item['stage'], dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise OperationDenied('Temporary publication file remains; manual review required')

    @contextmanager
    def _verified(self):
        self._eligible()
        item, replacement = self._record()
        parent = os.open(self.destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = None
        try:
            fd = os.open(item['archive'], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=parent)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise OperationDenied('Regular published archive required')
            identity = file_identity(before)
            self._unchanged(parent, fd, item, identity)
            validation = validate_archive(None, source_fd=fd)
            if validation.sha256 != item['sha256']:
                raise OperationDenied('Published archive differs from verified backup')
            self._unchanged(parent, fd, item, identity)
            token = hashlib.sha256(json.dumps(
                {'record': item, 'replacement': replacement, 'identity': identity},
                sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            older_state = 'NONE'
            if replacement:
                try:
                    old = os.stat(item['original'], dir_fd=parent, follow_symlinks=False)
                    older_state = ('UNCHANGED' if stat.S_ISREG(old.st_mode)
                                   and file_identity(old) == item['identity'] else 'CHANGED')
                except FileNotFoundError:
                    older_state = 'ABSENT'
            report = {'archive': item['archive'], 'sha256': validation.sha256,
                      'retained_older_archive': item.get('original') if older_state not in ('NONE', 'ABSENT') else None,
                      'older_archive_state': older_state,
                      'confirmation_token': token, 'original_result': 'FAILED'}
            yield report, item, replacement, parent, fd, identity
        finally:
            if fd is not None:
                os.close(fd)
            os.close(parent)

    def inspect(self):
        """Full read-only validation; errors leave every file and marker intact."""
        with operation_lock(self.state):
            with self._verified() as (report, *_):
                return report

    def keep_archives(self, expected_token, *, confirmed=False):
        """Future authenticated CSRF route must bind confirmation to inspect().

        Revalidates rather than trusting the earlier inspection. Retains every
        archive and never converts the original backup into SUCCESS. No host API
        or shell access is accepted by this coordinator.
        """
        if confirmed is not True:
            raise OperationDenied('Explicit recovery confirmation is required')
        with operation_lock(self.state):
            with self._verified() as (report, item, replacement, parent, fd, identity):
                if expected_token != report['confirmation_token']:
                    raise OperationDenied('Recovery details changed; verify and confirm again')
                message = ('Published archive fully reverified: ' + item['archive']
                           + '. User confirmed retaining all archives. Original backup remains FAILED.')
                if replacement:
                    message += ' No deletion of older archive: ' + item['original'] + '.'
                # Persist audit and origin knowledge before allowing new work.
                with EventLog(self.destination / 'Logs', 'Recovery',
                              datetime.now(timezone.utc)) as log:
                    log.write(message)
                    body = log.finish()
                self.history.add('PUBLICATION_RECOVERY', 'WARNING', body, item['archive'])
                ArchiveDiscovery(self.destination, self.state, self.history).remember_created(item['archive'])
                self._unchanged(parent, fd, item, identity)
                if self._record() != (item, replacement):
                    raise OperationDenied('Publication record changed; verify again')
                self.progress.resolve_cleanup()
                # Checkpoint BEFORE unlink: if interrupted, pending marker still
                # blocks backup, restore and archive deletion. Startup reblocks.
                with self.store.transaction() as operation:
                    operation.phase = Phase.FAILED
                try:
                    (intent.clear_replacement if replacement else intent.clear)(self.state)
                    if intent.pending(self.state):
                        raise OperationDenied('Publication record remains')
                except BaseException:
                    # An unlink followed by a failed directory fsync is ambiguous.
                    # Keep the operation blocked even if the name is now absent.
                    with self.store.transaction() as operation:
                        operation.phase = Phase.RECOVERY_REQUIRED
                    raise
                return {**report, 'cleanup_required': False}
