"""Restore coordinator with explicit, independently testable host adapters.

Writer and verifier must preserve/check data, ownership, ACL and xattrs in the
existing mounted dataset. No directory swapping, app.start or app.stop calls.
"""
from datetime import datetime, timezone
from pathlib import Path
from .locking import operation_lock
from .operations import OperationDenied, Phase
from .snapshots import Snapshots
from .plex import PlexStatus
from .eventlog import EventLog
from .staging import stage_archive
from .archive_store import NAME

class Restore:
    def __init__(self,api,store,history,progress,state_directory,destination,dataset,
                 database_check,write_config,verify_config,verify_rollback):
        self.api,self.store,self.history,self.progress=api,store,history,progress
        self.state=Path(state_directory); self.destination=Path(destination); self.dataset=dataset
        self.database_check=database_check; self.write_config=write_config
        self.verify_config=verify_config; self.verify_rollback=verify_rollback

    def run(self,name,confirmation):
        if not isinstance(name,str) or not NAME.fullmatch(name) or confirmation!='RESTORE':
            raise OperationDenied('Select archive and type RESTORE')
        with operation_lock(self.state):
            with self.store.transaction() as op:
                if op.kind!='RESTORE' or op.phase not in (Phase.WAITING_FOR_PLEX_STOP,Phase.READY):
                    raise OperationDenied('Validate archive first')
                digest=op.archive_identity
            if PlexStatus(self.api).read()['state']!='STOPPED':
                raise OperationDenied('Stop Plex manually before Restore')
            snapshots=Snapshots(self.api,self.store,self.dataset)
            modified=False; committed=False
            with EventLog(self.destination/'Logs','Restore',datetime.now(timezone.utc)) as log:
                try:
                    self.progress.start('RESTORE')
                    with stage_archive(self.destination/name,self.state,digest) as staged:
                        self.database_check(staged)
                        # Recheck after potentially lengthy archive/database work.
                        state=PlexStatus(self.api).read()['state']
                        with self.store.transaction() as op:
                            op.observe_plex(state)
                            op.confirm_restore(confirmation,state,digest)
                        self.progress.update('CREATING_SNAPSHOT')
                        identifier=snapshots.create()
                        log.write('Emergency snapshot created: '+identifier)
                        if PlexStatus(self.api).read()['state']!='STOPPED':
                            raise OperationDenied('Plex state changed before writing')
                        self.progress.update('RESTORING')
                        modified=True
                        self.write_config(staged)
                        self.progress.update('VERIFYING_RESTORE')
                        if self.verify_config(staged) is not True:
                            raise RuntimeError('Restored configuration verification failed')
                        if PlexStatus(self.api).read()['state']!='STOPPED':
                            raise OperationDenied('Plex no longer confirmed stopped')
                        self.progress.update('REMOVING_SNAPSHOT')
                        snapshots.remove()
                    committed=True
                    with self.store.transaction() as op: op.finish(True)
                    self.progress.update('COMPLETED')
                    log.write('Restore succeeded. Emergency snapshot absence confirmed. Plex remains stopped.')
                    self.history.add('RESTORE','SUCCESS',log.finish(),name)
                except Exception:
                    with self.store.transaction() as op: identifier=op.snapshot_id
                    if modified and identifier and not committed:
                        try:
                            self.progress.update('ROLLING_BACK')
                            snapshots.rollback()
                            if self.verify_rollback(identifier) is not True:
                                raise RuntimeError('Rollback verification failed')
                            log.write('Rollback verified. Emergency snapshot retained.')
                        except Exception:
                            log.write('Rollback could not be verified. Emergency snapshot retained.')
                    with self.store.transaction() as op:
                        op.phase=Phase.RECOVERY_REQUIRED if identifier or modified else Phase.FAILED
                    try: self.progress.update('CLEANUP_REQUIRED' if identifier or modified else 'FAILED')
                    except ValueError: pass
                    log.write('Restore failed. Plex was not started by this application.')
                    self.history.add('RESTORE','FAILED',log.finish(),name)
                    raise
