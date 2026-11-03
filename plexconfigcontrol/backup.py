"""Backup orchestration; host API and verified snapshot access are injected.

Supports new dated copies and explicitly confirmed replacement of one copy.
Replacement preserves the old file until the new archive is verified and the
temporary snapshot is confirmed absent. Interrupted publication blocks retries.
"""
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from .archives import archive_name
from .archive_store import ArchiveStore, ArchiveChanged
from .backup_archive import create_archive
from .eventlog import EventLog
from .archive_discovery import ArchiveDiscovery
from .locking import operation_lock
from .operations import Phase
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
    def __init__(self,api,store,history,progress,state_directory,destination,dataset,snapshot_reader):
        self.api,self.store,self.history,self.progress=api,store,history,progress
        self.state=Path(state_directory); self.destination=Path(destination)
        self.dataset=dataset
        # Context manager must expose ONLY this snapshot's immutable contents.
        self.snapshot_reader=snapshot_reader

    def run_new(self, *, create_another=None):
        """Create a dated copy after resolving the current single-copy prompt.

        create_another is the exact Archive identity displayed by that prompt,
        not a reusable boolean. Recount under the operation lock every time.
        Overwriting is a separate workflow and is not enabled by this method.
        """
        return self._run(create_another=create_another)

    def run_overwrite(self, selected):
        """The exact Archive selected in the overwrite confirmation is required."""
        if selected is None:
            raise ValueError('Select and confirm the existing archive')
        return self._run(overwrite=selected)

    def _run(self, *, create_another=None, overwrite=None):
        with operation_lock(self.state):
            if publication_intent.pending(self.state):
                raise RuntimeError('Unresolved archive publication requires recovery')
            archives = ArchiveStore(self.destination, self.state).list()
            selected = overwrite if overwrite is not None else create_another
            if selected is not None:
                if len(archives) != 1 or archives[0] != selected:
                    raise ArchiveChanged('Archives changed; refresh and choose again')
            elif len(archives) == 1:
                raise BackupDecisionRequired(archives[0])
            started=datetime.now(timezone.utc); name=archive_name(started)
            if (self.destination/name).exists() or (self.destination/name).is_symlink():
                raise ArchiveNameCollision('Archive filename already exists; choose another timestamp')
            original_identity = capture_original(self.destination, overwrite) if overwrite is not None else None
            with self.store.transaction() as operation: operation.begin('BACKUP')
            log=None; published=False
            snapshots=Snapshots(self.api,self.store,self.dataset)
            try:
                log=EventLog(self.destination/'Logs','Backup',started)
                self.progress.start('BACKUP')
                log.write('Backup started. Plex will not be stopped.')
                with self.store.transaction() as operation: operation.begin_backup()
                self.progress.update('CREATING_SNAPSHOT')
                identifier=snapshots.create()
                log.write('Temporary snapshot created: '+identifier)
                with tempfile.TemporaryDirectory(prefix='backup-',dir=self.state) as workspace:
                    output=Path(workspace)/'archive.tar.gz'
                    self.progress.update('CREATING_ARCHIVE')
                    with self.snapshot_reader(identifier) as snapshot_path:
                        result=create_archive(snapshot_path,output)
                    log.write('Archive verified against snapshot contents.')
                    self.progress.update('REMOVING_SNAPSHOT')
                    snapshots.remove()
                    log.write('Temporary snapshot absence confirmed.')
                    # Persist staging identity before destination file creation.
                    def intent(stage):
                        if overwrite is None:
                            publication_intent.record(self.state,stage,name,result.sha256)
                        else:
                            publication_intent.record_replacement(
                                self.state, stage, name, result.sha256,
                                overwrite.name, original_identity)
                    publish_new(output,self.destination,name,result.sha256,intent)
                    published=True
                    ArchiveDiscovery(self.destination,self.state,self.history).remember_created(name)
                    if overwrite is not None:
                        self.progress.update('VERIFYING_ARCHIVE')
                        retire_original(self.destination, overwrite, original_identity,
                                        name, result.sha256)
                        log.write('Verified replacement: '+overwrite.name+' -> '+name)
                if overwrite is None:
                    publication_intent.clear(self.state)
                else:
                    publication_intent.clear_replacement(self.state)
                with self.store.transaction() as operation: operation.finish(True)
                self.progress.update('COMPLETED')
                log.write('Backup completed successfully: '+name)
                self.history.add('BACKUP','SUCCESS',log.finish(),name)
                return name
            except Exception:
                cleanup_ok=True
                try:
                    with self.store.transaction() as operation: outstanding=operation.snapshot_id
                    if outstanding: snapshots.remove()
                except Exception:
                    cleanup_ok=False
                if publication_intent.pending(self.state):
                    cleanup_ok=False
                with self.store.transaction() as operation:
                    operation.phase=Phase.FAILED if cleanup_ok and not published else Phase.RECOVERY_REQUIRED
                try: self.progress.update('FAILED' if cleanup_ok and not published else 'CLEANUP_REQUIRED')
                except ValueError: pass
                if log:
                    with self.store.transaction() as operation:
                        remaining = operation.snapshot_id
                    log.write('Backup failed. '+('Temporary snapshot remains or needs verification: '+remaining
                              if remaining else 'Temporary snapshot absence confirmed.'))
                    if publication_intent.pending(self.state):
                        log.write('Archive publication requires review; existing archives were not automatically cleaned up.')
                    self.history.add('BACKUP','FAILED',log.finish(),name)
                raise
            finally:
                if log: log.finish()
