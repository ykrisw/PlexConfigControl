"""Read-only web representation; no mutation capability is granted here."""
from .locking import operation_lock, OperationBusy
from .publication_intent import describe
from .outcome import describe_outcome


def recovery_status(store, inspector=None):
    def read_identity():
        # Consistent app-owned state/marker pair. Never hold this lock while an
        # injected Recovery.inspect acquires its own lock for an API read.
        with operation_lock(store.directory):
            with store.transaction() as operation:
                identity = (operation.snapshot_id, operation.phase.value, operation.kind,
                            describe_outcome(operation.outcome,operation.kind) if operation.kind in ('BACKUP','RESTORE') else None)
            return identity, describe(store.directory)

    identity, publication = read_identity()
    identifier, phase, kind, outcome = identity
    result = {'phase':phase, 'kind':kind, 'snapshot_id':identifier,
              'snapshot_state':'UNKNOWN' if identifier else 'NONE',
              'removal_available':False, 'removal_supported':False,
              'publication':publication, 'publication_resolution_supported':False,
              'outcome':outcome,
              'confirmation_required':True,
              'reason':'RECOVERY_INSPECTION_UNAVAILABLE' if identifier else 'NO_RETAINED_SNAPSHOT',
              'loses_restore_recovery_point':bool(identifier) and kind=='RESTORE'}
    if inspector is not None and phase=='RECOVERY_REQUIRED' and identifier:
        # The inspector is injected by deployment code, never selected by a
        # browser request. It must expose only Recovery.inspect, not a root API.
        checked = inspector()
        if (isinstance(checked,dict) and checked.get('snapshot_id')==identifier
                and checked.get('phase')==phase
                and checked.get('kind')==kind
                and checked.get('snapshot_state') in ('PRESENT','ABSENT','UNKNOWN')):
            result['snapshot_state']=checked['snapshot_state']
            result['reason']=checked.get('reason')
    if read_identity() != (identity, publication):
        raise OperationBusy('Recovery changed during inspection; refresh status')
    return result
