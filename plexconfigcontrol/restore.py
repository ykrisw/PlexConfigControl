"""Restore coordinator with explicit, independently testable host adapters.

Writer and verifier must preserve/check data, ownership, ACL and xattrs in the
existing mounted dataset. No directory swapping, app.start or app.stop calls.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
from .locking import operation_lock
from .operations import OperationDenied, Phase
from .snapshots import Snapshots
from .plex import PlexStatus
from .eventlog import EventLog
from .staging import stage_archive
from .archive_store import NAME, archive_matches
from .publication_intent import pending

class Restore:
    def __init__(self,api,store,history,progress,state_directory,destination,dataset,
                 database_check,write_config,verify_config,verify_rollback):
        self.api,self.store,self.history,self.progress=api,store,history,progress
        self.state=Path(state_directory); self.destination=Path(destination)
        self._operation_guard=operation_lock
        self._execution_request_id=None
        self.dataset=dataset
        self.database_check=database_check; self.write_config=write_config
        self.verify_config=verify_config; self.verify_rollback=verify_rollback

    def run(self,name,confirmation):
        if not isinstance(name,str) or not NAME.fullmatch(name) or confirmation!='RESTORE':
            raise OperationDenied('Select archive and type RESTORE')
        with self._operation_guard(self.state):
            if pending(self.state):
                raise OperationDenied('Unresolved archive publication requires recovery')
            with self.store.transaction() as op:
                if op.kind!='RESTORE' or op.phase not in (Phase.WAITING_FOR_PLEX_STOP,Phase.READY):
                    raise OperationDenied('Validate archive first')
                if op.outcome is not None:
                    raise OperationDenied('Previous Restore execution requires recovery')
                digest=op.archive_identity
                details=op.validation_details or {}
                if (op.snapshot_id or not digest or details.get('status')!='VALID'
                        or details.get('archive')!=name or details.get('sha256')!=digest):
                    raise OperationDenied('Validate the selected archive first')
                identity=details.get('file_identity')
            if not archive_matches(self.destination,name,identity):
                raise OperationDenied('Archive changed; validate the returned copy again')
            if PlexStatus(self.api).read()['state']!='STOPPED':
                raise OperationDenied('Stop Plex manually before Restore')
            snapshots=Snapshots(self.api,self.store,self.dataset)
            modified=False; committed=False
            with EventLog(self.destination/'Logs','Restore',datetime.now(timezone.utc)) as log:
                try:
                    with self.store.transaction() as op:
                        op.execution_request_id=self._execution_request_id
                        op.outcome={'code':'RESTORE_IN_PROGRESS','archive':name}
                    self.progress.start('RESTORE')
                    with stage_archive(self.destination/name,self.state,digest,
                                       progress_callback=self.progress.update) as staged:
                        self.database_check(staged)
                        if not archive_matches(self.destination,name,identity):
                            raise OperationDenied('Archive changed; validate the returned copy again')
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
                    # Complete private staging cleanup while recovery is still
                    # available. Its context manager may fail during removal.
                    if self._workspace_pending():
                        raise RuntimeError('Private restore workspace cleanup requires verification')
                    if PlexStatus(self.api).read()['state']!='STOPPED':
                        raise OperationDenied('Plex no longer confirmed stopped')
                    self.progress.update('REMOVING_SNAPSHOT')
                    snapshots.remove()
                    committed=True
                    self.progress.update('COMPLETED')
                    log.write('Restore succeeded. Emergency snapshot absence confirmed. Plex remains stopped.')
                    self.history.add('RESTORE','SUCCESS',log.finish(),name)
                    with self.store.transaction() as op:
                        op.finish(True)
                        op.outcome={'code':'RESTORE_COMPLETED','archive':name}
                except Exception:
                    with self.store.transaction() as op: identifier=op.snapshot_id
                    rollback_message='';rollback_verified=False
                    if modified and identifier and not committed:
                        # A progress-database failure must not prevent rollback.
                        try: self.progress.update('ROLLING_BACK')
                        except Exception: pass
                        try:
                            snapshots.rollback()
                            if self.verify_rollback(identifier) is not True:
                                raise RuntimeError('Rollback verification failed')
                            rollback_verified=True
                            rollback_message='Rollback verified. Emergency snapshot retained. '
                        except Exception:
                            rollback_message='Rollback could not be verified. Emergency snapshot intent retained; presence requires verification. '
                    try: workspace_pending=self._workspace_pending()
                    except OSError: workspace_pending=True
                    cleanup_required=bool(identifier or modified or workspace_pending)
                    with self.store.transaction() as op:
                        op.phase=Phase.RECOVERY_REQUIRED if cleanup_required else Phase.FAILED
                        code=('RESTORE_VERIFIED_REPORTING_FAILED' if committed else
                              'RESTORE_ROLLBACK_VERIFIED' if rollback_verified else
                              'RESTORE_FAILED_UNCHANGED' if not modified else
                              'RESTORE_RECOVERY_UNCONFIRMED')
                        op.outcome={'code':code,'archive':name}
                    try: self.progress.fail_closed(cleanup_required)
                    except Exception: pass
                    message=rollback_message+'Restore failed. Plex was not started by this application. '
                    if identifier:
                        message+='Retained snapshot intent: '+identifier+'. '
                    elif committed:
                        message+='Configuration verification and snapshot removal completed; final operation reporting failed. '
                    elif modified:
                        message+='No snapshot is recorded; modified configuration needs manual verification. '
                    else:
                        message+='Configuration was not modified. '
                    if workspace_pending:
                        message+='Private restore workspace cleanup requires verification. '
                    body=self._record_failure(log,message)
                    # Reporting errors must not mask the original exception or
                    # leave the operation marked successful. Keep the durable
                    # state blocked even when History itself is unavailable.
                    try: self.history.add('RESTORE','FAILED',body,name)
                    except Exception: pass
                    raise

    def _workspace_pending(self):
        # scandir raises on unreadable state storage; glob may suppress errors
        # on some Python versions and therefore cannot prove cleanup here.
        with os.scandir(self.state) as entries:
            return any(entry.name.startswith('restore-') for entry in entries)

    def _record_failure(self,log,message):
        """Never append to a finalized permanent log, including after I/O errors."""
        if not log.closed:
            try:
                log.write(message)
                return log.finish()
            except Exception:
                try: log.finish()
                except Exception: pass
        # A finalization/history failure may follow closing the Restore log.
        # Record that failure separately rather than rewriting the closed file.
        message+='Original operation log: '+log.name+'. '
        try:
            with EventLog(self.destination/'Logs','Recovery',datetime.now(timezone.utc)) as recovery:
                recovery.write(message)
                return recovery.finish()
        except Exception:
            return message+'Permanent failure log could not be finalized; inspect operation state and existing logs.'
