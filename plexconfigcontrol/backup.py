"""Backup orchestration; host API and verified snapshot access are injected.

Supports new dated copies and requires an explicit current-file decision when
one copy exists. The overwrite workflow is not implemented here yet.
"""
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from .archives import archive_name
from .archive_store import ArchiveStore, ArchiveChanged
from .backup_archive import create_archive
from .eventlog import EventLog
from .locking import operation_lock
from .operations import Phase
from .publish import publish_new
from .snapshots import Snapshots
from . import publication_intent

class BackupDecisionRequired(RuntimeError):
    """Exactly one copy exists; the UI must offer overwrite or another copy."""
    def __init__(self, archive):
        super().__init__('Choose whether to overwrite the existing archive or create another copy')
        self.archive = archive

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
        with operation_lock(self.state):
            if publication_intent.pending(self.state):
                raise RuntimeError('Unresolved archive publication requires recovery')
            archives = ArchiveStore(self.destination, self.state).list()
            if create_another is not None:
                if len(archives) != 1 or archives[0] != create_another:
                    raise ArchiveChanged('Archives changed; refresh and choose again')
            elif len(archives) == 1:
                raise BackupDecisionRequired(archives[0])
            with self.store.transaction() as operation: operation.begin('BACKUP')
            started=datetime.now(timezone.utc); name=archive_name(started)
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
                        publication_intent.record(self.state,stage,name)
                    publish_new(output,self.destination,name,result.sha256,intent)
                    published=True
                publication_intent.clear(self.state)
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
                    log.write('Backup failed. '+('Snapshot cleanup confirmed.' if cleanup_ok else 'Snapshot cleanup requires attention.'))
                    self.history.add('BACKUP','FAILED',log.finish(),name)
                raise
            finally:
                if log: log.finish()
