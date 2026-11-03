"""Authenticated read-only checks, not authorization for host execution."""
from datetime import datetime, timezone

from .locking import OperationBusy
from .recovery_status import recovery_status


def inspect_integration(store, archives=None, plex=None, snapshot_inspector=None):
    result = {
        'schema': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
        'plex': {'configured': plex is not None, 'state': 'NOT_CHECKED', 'app_state': 'UNKNOWN'},
        'archives': {'configured': archives is not None, 'state': 'NOT_CHECKED', 'count': None},
        'snapshot': {'configured': snapshot_inspector is not None, 'state': 'NOT_CHECKED'},
        'operation': {'state': 'UNKNOWN', 'phase': None},
        # Read success never enables a write capability in this runtime.
        'backup_available': False, 'restore_available': False,
        'execution_reason': 'HOST_EXECUTION_NOT_CONNECTED',
    }
    def identity(value):
        return tuple(value.get(key) for key in ('phase', 'kind', 'snapshot_id', 'publication', 'outcome'))
    try:
        baseline = recovery_status(store, None)
    except OperationBusy:
        result['operation']['state'] = 'BUSY'
        return result
    except Exception:
        return result
    phase = baseline['phase']
    execution_pending = (baseline.get('outcome') or {}).get('code') == 'RESTORE_IN_PROGRESS'
    result['operation'] = {'phase': phase, 'state':
        'ACTIVE' if phase in ('VALIDATING', 'RUNNING') or execution_pending else
        'RECOVERY_REQUIRED' if phase == 'RECOVERY_REQUIRED' or baseline['snapshot_id']
                              or baseline['publication']['pending'] else
        'WAITING_FOR_USER' if phase in ('READY', 'WAITING_FOR_PLEX_STOP') else 'IDLE'}
    if snapshot_inspector is None:
        result['snapshot']['state'] = 'NOT_CONFIGURED'
    elif not baseline['snapshot_id']:
        # No temporary snapshot is created merely to probe permissions.
        result['snapshot']['state'] = 'NO_RECORDED_SNAPSHOT'
    elif phase != 'RECOVERY_REQUIRED':
        result['snapshot']['state'] = 'NOT_CHECKED'
    else:
        try:
            checked = recovery_status(store, snapshot_inspector)
            if identity(checked) != identity(baseline):
                result['operation'] = {'state': 'CHANGED', 'phase': None}
                return result
            result['snapshot']['state'] = checked['snapshot_state']
        except OperationBusy:
            result['operation'] = {'state': 'BUSY', 'phase': None}
            return result
        except Exception:
            result['snapshot']['state'] = 'UNKNOWN'
    if plex is None:
        result['plex']['state'] = 'NOT_CONFIGURED'
    else:
        try:
            status = plex.read()
            if (status.get('available') is True and status.get('state') in
                    ('RUNNING', 'STOPPED', 'DEPLOYING', 'STOPPING', 'CRASHED')):
                result['plex'].update(state='READ_VERIFIED', app_state=status['state'])
            else:
                result['plex']['state'] = 'UNAVAILABLE'
        except Exception:
            result['plex']['state'] = 'UNAVAILABLE'
    if archives is None:
        result['archives']['state'] = 'NOT_CONFIGURED'
    else:
        try:
            # Listing only: never read archive content or invoke import logging.
            result['archives'].update(state='LIST_VERIFIED', count=len(archives.list()))
        except Exception:
            result['archives']['state'] = 'UNAVAILABLE'
    try:
        latest = recovery_status(store, None)
        if identity(latest) != identity(baseline):
            result['operation'] = {'state': 'CHANGED', 'phase': None}
            result['snapshot']['state'] = 'UNKNOWN'
    except OperationBusy:
        result['operation'] = {'state': 'BUSY', 'phase': None}
        result['snapshot']['state'] = 'NOT_CHECKED'
    except Exception:
        result['operation'] = {'state': 'UNKNOWN', 'phase': None}
        result['snapshot']['state'] = 'UNKNOWN'
    return result
