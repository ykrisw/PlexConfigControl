"""Fail-closed operation rules. No host commands or automatic Plex start/stop."""
from dataclasses import dataclass
from enum import Enum


class Phase(str, Enum):
    IDLE = 'IDLE'
    VALIDATING = 'VALIDATING'
    WAITING_FOR_PLEX_STOP = 'WAITING_FOR_PLEX_STOP'
    READY = 'READY'
    RUNNING = 'RUNNING'
    RECOVERY_REQUIRED = 'RECOVERY_REQUIRED'
    SUCCESS = 'SUCCESS'
    FAILED = 'FAILED'


class OperationDenied(RuntimeError):
    pass


@dataclass
class Operation:
    """Persist this record atomically before any external side effect.

    The coordinator must serialize all changes under an exclusive process lock.
    Snapshot intent is stored before API creation; an ambiguous API result must
    retain that intent until absence or ownership has been reconciled.
    """
    phase: Phase = Phase.IDLE
    kind: str | None = None
    archive_identity: str | None = None
    snapshot_id: str | None = None
    validation_details: dict | None = None

    def begin(self, kind: str) -> None:
        if kind not in ('BACKUP', 'RESTORE'):
            raise OperationDenied('Unsupported operation')
        if self.snapshot_id or self.phase not in (Phase.IDLE, Phase.SUCCESS, Phase.FAILED):
            raise OperationDenied('Previous operation is unresolved')
        self.kind = kind
        self.archive_identity = None
        self.validation_details = None
        self.phase = Phase.VALIDATING

    def archive_validated(self, identity: str) -> None:
        if self.kind != 'RESTORE' or self.phase != Phase.VALIDATING or not identity:
            raise OperationDenied('Unexpected validation result')
        self.archive_identity = identity
        self.phase = Phase.WAITING_FOR_PLEX_STOP

    def observe_plex(self, state: str) -> None:
        if self.kind == 'RESTORE' and self.phase in (Phase.WAITING_FOR_PLEX_STOP, Phase.READY):
            self.phase = Phase.READY if state == 'STOPPED' else Phase.WAITING_FOR_PLEX_STOP

    def confirm_restore(self, text: str, plex_state: str, archive_identity: str) -> None:
        if (self.kind != 'RESTORE' or self.phase != Phase.READY
                or text != 'RESTORE' or plex_state != 'STOPPED'
                or not self.archive_identity or archive_identity != self.archive_identity):
            raise OperationDenied('Restore requires a validated unchanged archive, STOPPED Plex and RESTORE')
        self.phase = Phase.RUNNING

    def begin_backup(self) -> None:
        if self.kind != 'BACKUP' or self.phase != Phase.VALIDATING:
            raise OperationDenied('Unexpected backup state')
        self.phase = Phase.RUNNING

    def record_snapshot_intent(self, dataset: str, snapshot_name: str) -> None:
        if (self.phase != Phase.RUNNING or self.snapshot_id
                or not dataset or '@' in dataset
                or not snapshot_name.startswith('pcc-')
                or any(c in snapshot_name for c in '/@')
                or any(c.isspace() for c in snapshot_name)):
            raise OperationDenied('Invalid snapshot intent')
        self.snapshot_id = f'{dataset}@{snapshot_name}'

    def confirm_snapshot_absent(self, snapshot_id: str) -> None:
        if not self.snapshot_id or snapshot_id != self.snapshot_id:
            raise OperationDenied('Snapshot identity mismatch')
        self.snapshot_id = None

    def finish(self, verified: bool) -> None:
        if self.phase != Phase.RUNNING:
            raise OperationDenied('Operation is not running')
        if self.snapshot_id:
            self.phase = Phase.RECOVERY_REQUIRED
        else:
            self.phase = Phase.SUCCESS if verified else Phase.FAILED
