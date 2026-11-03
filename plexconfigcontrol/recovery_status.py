"""Read-only web representation; no mutation capability is granted here."""
def recovery_status(store, inspector=None):
    with store.transaction() as operation:
        identifier, phase, kind = operation.snapshot_id, operation.phase.value, operation.kind
    result = {'phase':phase, 'kind':kind, 'snapshot_id':identifier,
              'snapshot_state':'UNKNOWN' if identifier else 'NONE',
              'removal_available':False, 'removal_supported':False,
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
    return result
