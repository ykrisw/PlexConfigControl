"""Backup orchestration; host API and verified snapshot access are injected.

Supports new dated copies and explicitly confirmed replacement of one copy.
Replacement preserves the old file until the new archive is verified and the
temporary snapshot is confirmed absent. Interrupted publication blocks retries.
"""
import tempfile
import os
from datetime import datetime, timezone
from pathlib import Path
from .archives import archive_name
from .naming import load_naming, archive_prefix as validate_prefix
from .archive_store import ArchiveStore, ArchiveChanged
from .backup_archive import create_archive
from .eventlog import EventLog
from .archive_discovery import ArchiveDiscovery
from .locking import operation_lock
from .operations import Phase, OperationDenied
from .plex import PlexStatus
from .publish import publish_new, capture_original, retire_original
from .snapshots import Snapshots
from . import publication_intent

class BackupDecisionRequired(RuntimeError):
    """Exactly one copy exists; the UI must offer overwrite or another copy."""
    def __init__(self, archive):
        super().__init__('Choose whether to overwrite the existing archive or create another copy')
        self.archive = archive

class ArchiveNameCollision(RuntimeError):
    """A dated filename already exists; the user must choose another timestamp."""


class Backup:
    def __init__(self,api,store,history,progress,state_directory,destination,dataset,snapshot_reader, *, archive_prefix=None):
        self.api,self.store,self.history,self.progress=api,store,history,progress
        self.state=Path(state_directory); self.destination=Path(destination)
        self._operation_guard=operation_lock
        self._execution_request_id=None
        self.dataset=dataset
        self.archive_prefix=validate_prefix(load_naming(self.state).archive_prefix if archive_prefix is None else archive_prefix)
        # Context manager must expose ONLY this snapshot's immutable contents.
        self.snapshot_reader=snapshot_reader

    def run_new(self, *, create_another=None, prefix=None):
        """Create a dated copy after resolving the current single-copy prompt.

        create_another is the exact Archive identity displayed by that prompt,
        not a reusable boolean. Recount under the operation lock every time.
        Overwriting is a separate workflow and is not enabled by this method.
        """
        return self._run(create_another=create_another,prefix=prefix)

    def run_overwrite(self, selected, *, prefix=None):
        """The exact Archive selected in the overwrite confirmation is required."""
        if selected is None:
            raise ValueError('Select and confirm the existing archive')
        return self._run(overwrite=selected,prefix=prefix)

    def _run(self, *, create_another=None, overwrite=None, prefix=None):
        prefix = self.archive_prefix if prefix is None else validate_prefix(prefix)
        with self._operation_guard(self.state):
            if publication_intent.pending(self.state):
                raise RuntimeError('Unresolved archive publication requires recovery')
            archives = ArchiveStore(self.destination, self.state).list()
            selected = overwrite if overwrite is not None else create_another
            if selected is not None:
                if len(archives) != 1 or archives[0] != selected:
                    raise ArchiveChanged('Archives changed; refresh and choose again')
            elif len(archives) == 1:
                raise BackupDecisionRequired(archives[0])
            started=datetime.now(timezone.utc); name=archive_name(started,prefix=prefix)
            if (self.destination/name).exists() or (self.destination/name).is_symlink():
                raise ArchiveNameCollision('Archive filename already exists; choose another timestamp')
            if PlexStatus(self.api).read()['state'] != 'RUNNING':
                raise OperationDenied('Plex must be confirmed RUNNING before Backup')
            original_identity = capture_original(self.destination, overwrite) if overwrite is not None else None
            with self.store.transaction() as operation:
                operation.begin('BACKUP')
                operation.execution_request_id=self._execution_request_id
                operation.outcome={'code':'BACKUP_IN_PROGRESS','archive':name}
            log=None; published=False; stage_identity=None; result=None
            snapshots=Snapshots(self.api,self.store,self.dataset)
            try:
                log=EventLog(self.destination/'Logs','Backup',started)
                self.progress.start('BACKUP')
                log.write('Backup started. Plex will not be stopped.')
                with self.store.transaction() as operation: operation.begin_backup()
                self.progress.update('CREATING_SNAPSHOT')
                if PlexStatus(self.api).read()['state'] != 'RUNNING':
                    raise OperationDenied('Plex is no longer confirmed RUNNING before snapshot creation')
                identifier=snapshots.create()
                log.write('Temporary snapshot created: '+identifier)
                with tempfile.TemporaryDirectory(prefix='backup-',dir=self.state) as workspace:
                    output=Path(workspace)/'archive.tar.gz'
                    self.progress.update('CREATING_ARCHIVE')
                    with self.snapshot_reader(identifier) as snapshot_path:
                        result=create_archive(snapshot_path,output,verification_progress=lambda done,total:
                            self.progress.update('VERIFYING_ARCHIVE',done=done,total=total))
                    log.write('Archive verified against snapshot contents.')
                    self.progress.update('REMOVING_SNAPSHOT')
                    snapshots.remove()
                    log.write('Temporary snapshot absence confirmed.')
                    # Persist staging identity before destination file creation.
                    def intent(stage):
                        nonlocal stage_identity
                        stage_identity=stage
                        if overwrite is None:
                            publication_intent.record(self.state,stage,name,result.sha256)
                        else:
                            publication_intent.record_replacement(
                                self.state, stage, name, result.sha256,
                                overwrite.name, original_identity)
                    self.progress.update('PUBLISHING_ARCHIVE')
                    publish_new(output,self.destination,name,result.sha256,intent)
                    published=True
                    ArchiveDiscovery(self.destination,self.state,self.history).remember_created(name)
                if self._workspace_pending():
                    raise RuntimeError('Private backup workspace cleanup requires verification')
                if overwrite is not None:
                    self.progress.update('VERIFYING_ARCHIVE')
                    retire_original(self.destination, overwrite, original_identity,
                                    name, result.sha256)
                    log.write('Verified replacement: '+overwrite.name+' -> '+name)
                if overwrite is None:
                    publication_intent.clear(self.state)
                else:
                    publication_intent.clear_replacement(self.state)
                self.progress.update('COMPLETED')
                log.write('Backup completed successfully: '+name)
                self.history.add('BACKUP','SUCCESS',log.finish(),name)
                # Keep RUNNING until durable reporting has returned, so an
                # interruption is reconciled at startup rather than hidden.
                with self.store.transaction() as operation:
                    operation.finish(True)
                    operation.outcome={'code':'BACKUP_COMPLETED','archive':name}
                return name
            except Exception:
                cleanup_ok=True
                try:
                    with self.store.transaction() as operation: outstanding=operation.snapshot_id
                    if outstanding: snapshots.remove()
                except Exception:
                    cleanup_ok=False
                # A reporting failure may happen after the original intent was
                # cleared. Preserve the same known digest/names for confirmed
                # recovery; never republish, rehash a replacement as trusted,
                # overwrite a marker or delete an archive during this handling.
                if published and not publication_intent.pending(self.state):
                    try:
                        if stage_identity is None or result is None:
                            raise RuntimeError('Verified publication identity is unavailable')
                        intent(stage_identity)
                    except Exception:
                        cleanup_ok=False
                try: workspace_pending=self._workspace_pending()
                except OSError: workspace_pending=True
                if workspace_pending or publication_intent.pending(self.state):
                    cleanup_ok=False
                cleanup_required=not cleanup_ok or published
                with self.store.transaction() as operation:
                    operation.phase=Phase.RECOVERY_REQUIRED if cleanup_required else Phase.FAILED
                    remaining=operation.snapshot_id
                    code=('BACKUP_PUBLISHED_REVIEW' if published else
                          'BACKUP_PUBLICATION_UNCERTAIN' if publication_intent.pending(self.state) else
                          'BACKUP_FAILED')
                    operation.outcome={'code':code,'archive':name}
                try: self.progress.fail_closed(cleanup_required)
                except Exception: pass
                message='Backup failed. '
                message+=('Temporary snapshot remains or needs verification: '+remaining+'. '
                          if remaining else 'No temporary snapshot is recorded for this operation. ')
                if published:
                    message+='Published archive retained for verification: '+name+'. '
                if publication_intent.pending(self.state):
                    message+='Archive publication requires review; no archive was deleted by failure cleanup. '
                if workspace_pending:
                    message+='Private backup workspace cleanup requires verification. '
                if log:
                    body=self._record_failure(log,message)
                else:
                    body=message+'Permanent operation log could not be opened.'
                try: self.history.add('BACKUP','FAILED',body,name)
                except Exception: pass
                raise
            finally:
                if log: log.finish()

    def _workspace_pending(self):
        with os.scandir(self.state) as entries:
            return any(entry.name.startswith('backup-') for entry in entries)

    def _record_failure(self,log,message):
        """Keep finalized operation logs immutable, even after reporting errors."""
        if not log.closed:
            try:
                log.write(message)
                return log.finish()
            except Exception:
                try: log.finish()
                except Exception: pass
        message+='Original operation log: '+log.name+'. '
        try:
            with EventLog(self.destination/'Logs','Recovery',datetime.now(timezone.utc)) as recovery:
                recovery.write(message)
                return recovery.finish()
        except Exception:
            return message+'Permanent failure log could not be finalized; inspect operation state and existing logs.'
