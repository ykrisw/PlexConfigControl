"""Small allowlisted historical outcome; not proof of current file existence."""
from .archive_store import NAME

BACKUP_CODES = {
    'BACKUP_IN_PROGRESS', 'BACKUP_COMPLETED', 'BACKUP_FAILED',
    'BACKUP_PUBLISHED_REVIEW', 'BACKUP_PUBLICATION_UNCERTAIN',
    'BACKUP_RECONCILED', 'BACKUP_INTERRUPTED',
}

RESTORE_CODES = {
    'RESTORE_IN_PROGRESS', 'RESTORE_COMPLETED', 'RESTORE_FAILED_UNCHANGED',
    'RESTORE_ROLLBACK_VERIFIED', 'RESTORE_RECOVERY_UNCONFIRMED',
    'RESTORE_VERIFIED_REPORTING_FAILED', 'RESTORE_INTERRUPTED',
}


def describe_outcome(value, kind=None):
    if not isinstance(value, dict) or set(value) != {'code', 'archive'}:
        return None
    code, archive = value['code'], value['archive']
    if not isinstance(code, str) or code not in BACKUP_CODES | RESTORE_CODES:
        return None
    if kind is not None and (kind not in ('BACKUP','RESTORE') or not code.startswith(kind+'_')):
        return None
    if archive is None and code in ('BACKUP_INTERRUPTED','RESTORE_INTERRUPTED'):
        return {'code': code, 'archive': None}
    if not isinstance(archive, str) or not NAME.fullmatch(archive):
        return None
    return {'code': code, 'archive': archive}
