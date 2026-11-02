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
        with self.store.transaction() as operation:
            return {'phase': operation.phase.value,
                    'kind': operation.kind,
                    'snapshot_id': operation.snapshot_id,
                    'removal_available': bool(operation.snapshot_id)
                    and operation.phase == Phase.RECOVERY_REQUIRED}

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
