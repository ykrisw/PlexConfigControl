"""Read-only backup choice for the UI; execution must recheck all identities."""
from dataclasses import asdict
from .archives import backup_action
from .archive_store import ArchiveStore
from .locking import operation_lock, OperationBusy
from .naming import load_naming
from .operations import Phase
from .publication_intent import pending


def plan_backup(destination, state_directory):
    with operation_lock(state_directory):
        archives = ArchiveStore(destination, state_directory)
        with archives.state.transaction() as operation:
            if (operation.snapshot_id or operation.phase not in
                    (Phase.IDLE, Phase.SUCCESS, Phase.FAILED) or pending(state_directory)):
                raise OperationBusy('Previous operation or recovery must finish')
        rows = archives.list()
        return {
            'archive_count': len(rows),
            'archive_prefix': load_naming(state_directory).archive_prefix,
            'action': backup_action(len(rows)),
            'existing_archive': asdict(rows[0]) if len(rows) == 1 else None,
            # Only creating another dated copy is executable at this stage.
            'overwrite_available': False,
        }
