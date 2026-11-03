"""Manual removal of a retained snapshot, serialized with all other operations."""
from .locking import operation_lock
from .operations import OperationDenied, Phase
from .snapshots import Snapshots


class Recovery:
    def __init__(self, api, store, history, state_directory, dataset):
        self.api = api
        self.store = store
        self.history = history
        self.state_directory = state_directory
        self.dataset = dataset

    def inspect(self):
        """Read-only, exact-identity preflight for the confirmation dialog.

        ABSENT still requires confirmation to reconcile retained intent after
        a lost deletion reply or removal in TrueNAS. UNKNOWN never enables an
        action and never exposes arbitrary transport errors to the browser.
        Inspection performs no cleanup, Plex control or snapshot mutations.
        """
        with operation_lock(self.state_directory):
            with self.store.transaction() as operation:
                phase, kind, identifier = operation.phase, operation.kind, operation.snapshot_id
            result = {'phase': phase.value, 'kind': kind, 'snapshot_id': identifier,
                      'snapshot_state': 'NONE', 'removal_available': False,
                      'confirmation_required': True, 'reason': 'NO_RETAINED_SNAPSHOT',
                      'loses_restore_recovery_point': kind == 'RESTORE' and bool(identifier)}
            if not identifier:
                return result
            if phase != Phase.RECOVERY_REQUIRED:
                result.update(snapshot_state='NOT_CHECKED', reason='OPERATION_NOT_IN_RECOVERY')
                return result
            try:
                exists = Snapshots(self.api, self.store, self.dataset).exists(identifier)
            except Exception:
                result.update(snapshot_state='UNKNOWN', reason='SNAPSHOT_STATE_UNAVAILABLE')
                return result
            result.update(snapshot_state='PRESENT' if exists else 'ABSENT',
                          removal_available=True, reason=None)
            return result

    def remove_snapshot(self, expected_snapshot, confirmed=False):
        """Web route must authenticate user and validate CSRF before calling.

        Confirmation includes exact snapshot identity from the displayed dialog.
        Successful removal never converts a failed Restore into SUCCESS and does
        not alone authorize a new operation: other cleanup must be reconciled.
        """
        if confirmed is not True:
            raise OperationDenied('Explicit removal confirmation is required')
        with operation_lock(self.state_directory):
            with self.store.transaction() as operation:
                if (operation.phase != Phase.RECOVERY_REQUIRED
                        or not operation.snapshot_id
                        or operation.snapshot_id != expected_snapshot):
                    raise OperationDenied('Snapshot or recovery state changed; refresh the dialog')
                kind = operation.kind
            # Record user intent before destructive API call. No secrets included.
            self.history.add('SNAPSHOT_REMOVAL', 'STARTED',
                             'Confirmed removal requested: ' + expected_snapshot)
            try:
                Snapshots(self.api, self.store, self.dataset).remove()
            except Exception:
                self.history.add('SNAPSHOT_REMOVAL', 'FAILED',
                                 'Removal not confirmed; reconcile snapshot: ' + expected_snapshot)
                raise
            self.history.add('SNAPSHOT_REMOVAL', 'SUCCESS',
                             'Snapshot absence confirmed: ' + expected_snapshot
                             + '. Original operation: ' + str(kind)
                             + '. Remaining operation cleanup still requires verification.')
            # RECOVERY_REQUIRED deliberately remains until the coordinator has
            # verified staging/temporary archive cleanup and final failure state.
            return {'removed': expected_snapshot, 'cleanup_required': True}
