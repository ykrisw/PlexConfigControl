"""Fail-closed startup reconciliation. Run before accepting operation requests."""
from .locking import operation_lock
from .operations import Phase
from .publication_intent import pending
from .outcome import describe_outcome


def reconcile_startup(store, progress, history, state_directory):
    """Mark interrupted work; never delete snapshots or restart Plex on startup.

    Must run once during service startup, not once per HTTP worker. The operation
    lock prevents misclassifying work owned by a live process as interrupted.
    Repeated invocation is idempotent after the durable state transition.
    """
    with operation_lock(state_directory):
        with store.transaction() as operation:
            phase=operation.phase
            previous=describe_outcome(operation.outcome,operation.kind)
            executing_restore=(operation.kind=='RESTORE' and previous is not None
                               and previous['code']=='RESTORE_IN_PROGRESS'
                               and phase in (Phase.WAITING_FOR_PLEX_STOP,Phase.READY))
            interrupted=(phase in (Phase.VALIDATING,Phase.RUNNING) or executing_restore or
                         (pending(state_directory) and phase != Phase.RECOVERY_REQUIRED))
            snapshot=operation.snapshot_id
            if not interrupted:
                return {'interrupted':False,'phase':phase.value,'snapshot_id':snapshot}
            # Even without a snapshot there may be a private workspace or a
            # destination staging file. Never silently allow another operation.
            operation.phase=Phase.RECOVERY_REQUIRED
            kind=operation.kind
            if kind in ('BACKUP','RESTORE'):
                archive=previous['archive'] if previous else (operation.validation_details or {}).get('archive')
                candidate={'code':kind+'_INTERRUPTED','archive':archive}
                operation.outcome=describe_outcome(candidate,kind) or {'code':kind+'_INTERRUPTED','archive':None}
            if kind=='RESTORE' and phase==Phase.VALIDATING and operation.validation_details:
                operation.validation_details={
                    'archive':operation.validation_details.get('archive'),
                    'status':'INTERRUPTED',
                    'reason':'Application restarted before validation completed'}
        try:
            progress.fail_closed(True)
        except ValueError:
            pass
        history.add('INTERRUPTED_OPERATION','FAILED',
                    'Application restarted during '+str(kind)+'. '
                    'Recovery and temporary-file verification required. '
                    'Snapshot: '+(snapshot or 'none recorded')+'. '
                    'No automatic Plex start/stop or destructive cleanup performed.')
        return {'interrupted':True,'phase':Phase.RECOVERY_REQUIRED.value,
                'snapshot_id':snapshot}
