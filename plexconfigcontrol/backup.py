"""Backup orchestration; host API and verified snapshot access are injected.

Initial path supports new dated copies. The single-existing-copy decision must
be resolved by the caller; overwrite is deliberately not implemented here yet.
"""
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from .archives import archive_name
from .backup_archive import create_archive
from .eventlog import EventLog
from .locking import operation_lock
from .operations import Phase
from .publish import publish_new
from .snapshots import Snapshots

class Backup:
    def __init__(self,api,store,history,progress,state_directory,destination,dataset,snapshot_reader):
        self.api,self.store,self.history,self.progress=api,store,history,progress
        self.state=Path(state_directory); self.destination=Path(destination)
        self.dataset=dataset
        # Context manager must expose ONLY this snapshot's immutable contents.
        self.snapshot_reader=snapshot_reader

    def run_new(self):
        with operation_lock(self.state):
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
                        with (self.state/'publication-intent.txt').open('w') as file:
                            import os
                            file.write(stage+'\n'+name+'\n'); file.flush(); os.fsync(file.fileno())
                    publish_new(output,self.destination,name,result.sha256,intent)
                    published=True
                (self.state/'publication-intent.txt').unlink(missing_ok=True)
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
                if (self.state/'publication-intent.txt').exists():
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
