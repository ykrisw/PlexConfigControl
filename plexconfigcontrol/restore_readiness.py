"""Advisory UI gating; Restore.run independently rechecks before any write."""
from .locking import operation_lock
from .operations import Phase
from .plex import PlexStatus
from .publication_intent import pending
from .archive_store import NAME, archive_matches


def restore_readiness(store, state_directory, api, archive_directory=None):
    with operation_lock(state_directory):
        # Network I/O must not hold a SQLite write transaction.
        plex=PlexStatus(api).read()
        with store.transaction() as operation:
            details=operation.validation_details or {}
            archive=details.get('archive')
            validated=(operation.kind=='RESTORE' and
                operation.phase in (Phase.WAITING_FOR_PLEX_STOP,Phase.READY) and
                details.get('status')=='VALID' and
                isinstance(archive,str) and NAME.fullmatch(archive) is not None and
                bool(operation.archive_identity) and
                operation.archive_identity==details.get('sha256'))
            unresolved=bool(operation.snapshot_id) or pending(state_directory)
            if unresolved:
                reason='RECOVERY_REQUIRED'
            elif not validated:
                reason='VALIDATE_ARCHIVE_FIRST'
            elif not archive_matches(archive_directory,archive,details.get('file_identity')):
                reason='ARCHIVE_CHANGED_REVALIDATE'
            elif plex['state']=='RUNNING':
                reason='STOP_PLEX_MANUALLY'
            elif plex['state']!='STOPPED':
                reason='PLEX_STOP_NOT_CONFIRMED'
            else:
                reason=None
            return {'ready':reason is None,'reason':reason,'plex':plex,
                    'archive':archive if validated else None,
                    'confirmation_text':'RESTORE',
                    'confirmation_required':True}
