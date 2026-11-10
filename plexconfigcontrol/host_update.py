"""Replace only the images of the full TrueNAS custom app."""
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
from types import SimpleNamespace
from uuid import uuid4

from .host_install import APP, APPS_MOUNT, InstallError, LocalMiddleware, _ready, require_truenas_version
from .locking import OperationBusy, operation_lock
from .plex_runtime import detect_plex_runtime
from .plex_storage import _zfs
from .publication_intent import pending


STATE = Path(APPS_MOUNT) / 'app_mounts' / APP / 'state'
RECORD = 'update-recovery.json'
REPOSITORIES = {'panel': 'plexconfigcontrol', 'worker': 'plexconfigcontrol-worker'}


def _installed(api):
    rows = api.call('app.query', [['name', '=', APP]], {'select': ['name', 'custom_app', 'state']})
    if len(rows) != 1 or rows[0]['name'] != APP or rows[0]['custom_app'] is not True:
        raise InstallError('Nie znaleziono pełnej instalacji PlexConfigControl w TrueNAS Apps.')
    return rows[0]['state']


def _details(compose):
    try:
        services = compose['services']
        panel, worker = services['panel'], services['worker']
        if set(services) != {'panel', 'worker', 'initialize-plex-sqlite'}:
            raise ValueError
        for name in REPOSITORIES:
            service = services[name]
            if (not re.fullmatch(REPOSITORIES[name] + r':[A-Za-z0-9._-]+', service['image'])
                    or service['pull_policy'] != 'never'):
                raise ValueError
            if [mount['source'] for mount in service['volumes']
                    if mount['target'] == '/var/lib/plexconfigcontrol'] != [str(STATE)]:
                raise ValueError
        verifier, = [Path(mount['source']) for mount in panel['volumes']
                     if mount['target'] == '/run/pcc-secrets/panel-verifier']
        private = verifier.parent
        if (verifier.name != 'panel-verifier' or private.parts[:2] != ('/', 'mnt')
                or private.resolve(strict=True) != private):
            raise ValueError
        mode = private.stat()
        if not stat.S_ISDIR(mode.st_mode) or mode.st_uid != 0 or mode.st_mode & 0o077:
            raise ValueError
        port, = panel['ports']
        endpoint = SimpleNamespace(state=str(STATE), host_ip=port['host_ip'], host_port=int(port['published']))
    except (KeyError, TypeError, ValueError, OSError):
        raise InstallError('Konfiguracja aplikacji różni się od pełnej instalacji obsługiwanej przez kreator.') from None
    return private / RECORD, endpoint


def _ensure_idle():
    checks = (
        ('operations.sqlite3', 'SELECT payload FROM operation WHERE id=1'),
        ('execution.sqlite3', "SELECT state FROM requests WHERE state IN ('QUEUED','RUNNING','RECOVERY_REQUIRED')"),
    )
    rows = []
    for filename, query in checks:
        path = STATE / filename
        if not stat.S_ISREG(path.lstat().st_mode):
            raise InstallError('Nie można sprawdzić stanu operacji PlexConfigControl.')
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            rows.append(db.execute(query).fetchone())
    operation = json.loads(rows[0][0])
    if (operation['phase'] not in ('IDLE', 'SUCCESS', 'FAILED') or operation['snapshot_id']
            or rows[1] is not None or pending(STATE)):
        raise InstallError('Zakończ bieżącą operację lub odzyskiwanie przed aktualizacją.')


def _write_record(path, previous, candidate):
    temporary = path.with_name(f'.{RECORD}.{uuid4().hex}')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'previous': previous, 'candidate': candidate}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
        _sync_parent(path)
    finally:
        temporary.unlink(missing_ok=True)


def _sync_parent(path):
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _clear_record(path):
    path.unlink()
    _sync_parent(path)


def _ensure_no_app_job(api):
    jobs = api.call('core.get_jobs', [
        ['method', 'in', ['app.start', 'app.stop', 'app.update', 'app.redeploy', 'app.delete']],
        ['state', 'in', ['WAITING', 'RUNNING']],
    ], {'select': ['arguments']})
    if any(job['arguments'][:1] == [APP] for job in jobs):
        raise InstallError('TrueNAS nadal wykonuje zadanie PlexConfigControl. Spróbuj ponownie po jego zakończeniu.')


def _stop(api, expected, *, record=None, candidate=None):
    with operation_lock(STATE):
        _ensure_no_app_job(api)
        if api.call('app.config', APP) != expected:
            raise InstallError('Konfiguracja aplikacji zmieniła się. Uruchom kreator ponownie.')
        state = _installed(api)
        allowed = ('RUNNING',) if record is not None else ('RUNNING', 'STOPPED', 'DEPLOYING', 'CRASHED')
        if state not in allowed:
            raise InstallError('PlexConfigControl musi zakończyć uruchamianie lub zatrzymywanie.')
        _ensure_idle()
        if record is not None:
            _write_record(record, expected, candidate)
        if state != 'STOPPED':
            api.stop()
        if _installed(api) != 'STOPPED':
            raise InstallError('TrueNAS nie potwierdził zatrzymania PlexConfigControl.')


def _configure(api, compose):
    result = api.configure(compose)
    if (not isinstance(result, dict) or result.get('name') != APP
            or result.get('custom_app') is not True or api.call('app.config', APP) != compose):
        raise InstallError('TrueNAS nie potwierdził zmiany konfiguracji PlexConfigControl.')


def _recover(api, record, previous, candidate, endpoint):
    _ensure_no_app_job(api)
    current = api.call('app.config', APP)
    if current != previous and current != candidate:
        raise InstallError('Konfiguracja w TrueNAS zmieniła się poza kreatorem. Wymaga sprawdzenia.')
    if current != previous:
        _stop(api, current)
        _configure(api, previous)
    if _installed(api) == 'STOPPED':
        api.start()
    _ready(endpoint)
    _check_running_images(previous)
    _clear_record(record)


def _docker(*args):
    return subprocess.run(
        ['docker', *args], check=True, capture_output=True, text=True, timeout=20,
    ).stdout.splitlines()


def _inspect_images(compose):
    images = _docker('image', 'inspect', '--format', '{{.Id}}',
                     *(compose['services'][name]['image'] for name in REPOSITORIES))
    if len(images) != len(REPOSITORIES) or any(not re.fullmatch(r'sha256:[a-f0-9]{64}', item) for item in images):
        raise InstallError('Nie można potwierdzić obrazów PlexConfigControl.')
    return images


def _check_running_images(compose):
    for name, expected in zip(REPOSITORIES, _inspect_images(compose), strict=True):
        containers = _docker('ps', '-q', '--no-trunc',
                             '--filter', f'label=com.docker.compose.project=ix-{APP}',
                             '--filter', f'label=com.docker.compose.service={name}')
        if (len(containers) != 1
                or _docker('inspect', '--type', 'container', '--format', '{{.Image}}', containers[0]) != [expected]):
            raise InstallError('Uruchomione kontenery PlexConfigControl nie odpowiadają zapisanym obrazom.')


def _approve(prompt):
    if input(prompt).strip().lower() != 'tak':
        raise InstallError('Aktualizacja anulowana.')


def _update(api, *, check_only=False):
    require_truenas_version(api.call('system.version'))
    app_state = _installed(api)
    dataset = api.call('docker.config')['dataset']
    if (STATE.resolve(strict=True) != STATE
            or _zfs(api, APPS_MOUNT) != (dataset, APPS_MOUNT)
            or _zfs(api, str(STATE)) != (f'{dataset}/app_mounts/{APP}/state', str(STATE))
            or sorted(api.call('app.ix_volume.query', [['app_name', '=', APP]]), key=lambda item: item['name']) not in (
                [{'app_name': APP, 'name': 'state'}],
                [{'app_name': APP, 'name': 'pcc'}, {'app_name': APP, 'name': 'state'}],
            )):
        raise InstallError('Nie można potwierdzić istniejącego wolumenu ustawień PlexConfigControl.')
    previous = api.call('app.config', APP)
    record, endpoint = _details(previous)
    if os.path.lexists(record):
        if check_only:
            raise InstallError('Wykryto przerwaną aktualizację. Wybierz Aktualizuj, aby uruchomić odzyskiwanie.')
        info = record.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise InstallError('Plik poprzedniej aktualizacji wymaga sprawdzenia przez administratora.')
        saved = json.loads(record.read_text(encoding='utf-8'))
        if any(_details(saved[key])[0] != record for key in ('previous', 'candidate')):
            raise InstallError('Plik poprzedniej aktualizacji nie pasuje do tej instalacji.')
        _approve('Wykryto przerwaną aktualizację. Wpisz tak, aby uruchomić poprzednią wersję: ')
        _inspect_images(saved['previous'])
        _recover(api, record, saved['previous'], saved['candidate'], endpoint)
        print('Poprzednia wersja PlexConfigControl działa. Uruchom kreator ponownie, aby ją zaktualizować.')
        return
    if app_state != 'RUNNING':
        raise InstallError('Uruchom PlexConfigControl w TrueNAS Apps przed aktualizacją.')
    _ready(endpoint, timeout=10)
    with operation_lock(STATE):
        _ensure_no_app_job(api)
        _ensure_idle()
    reference, version, *_ = detect_plex_runtime()
    initializer = previous['services']['initialize-plex-sqlite']
    if (initializer['image'] != reference
            or initializer['environment']['PCC_SQLITE_VERSION'] != version):
        raise InstallError('Obraz Plexa zmienił się od instalacji. Ta aktualizacja wymaga zgodnego Plex SQLite.')

    _check_running_images(previous)
    if check_only:
        print('Wymagania aktualizacji spełnione. Budowa nowych obrazów zostanie sprawdzona podczas aktualizacji.')
        return
    _approve('Znaleziono pełny PlexConfigControl. Wpisz tak, aby go zaktualizować: ')
    tag = 'update-' + uuid4().hex
    panel, worker = (f'{repository}:{tag}' for repository in REPOSITORIES.values())
    subprocess.run(['sh', 'deploy/install.sh', '--build-update', panel, worker], check=True)
    if detect_plex_runtime()[:2] != (reference, version):
        raise InstallError('Obraz Plexa zmienił się podczas budowy. Uruchom kreator ponownie.')
    candidate = copy.deepcopy(previous)
    candidate['services']['panel']['image'] = panel
    candidate['services']['worker']['image'] = worker
    _inspect_images(candidate)
    try:
        _stop(api, previous, record=record, candidate=candidate)
        _configure(api, candidate)
        api.start()
        _ready(endpoint)
        _check_running_images(candidate)
    except (Exception, KeyboardInterrupt):
        if not record.exists():
            raise
        print('Aktualizacja przerwana. Przywracam poprzednie obrazy PlexConfigControl.', flush=True)
        try:
            _recover(api, record, previous, candidate, endpoint)
        except (Exception, KeyboardInterrupt):
            raise InstallError('Nie potwierdzono powrotu do poprzedniej wersji. Uruchom ponownie ten sam kreator.') from None
        raise InstallError('Aktualizacja nie powiodła się. Poprzednia wersja działa.') from None
    _clear_record(record)
    print(f'PlexConfigControl zaktualizowany. Otwórz https://{endpoint.host_ip}:{endpoint.host_port}')


def run_update(*, check_only=False):
    if os.geteuid() != 0:
        raise InstallError('Uruchom aktualizację jako administrator TrueNAS.')
    try:
        if check_only:
            return _update(LocalMiddleware(), check_only=True)
        fd = os.open('/run/plexconfigcontrol-update.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _update(LocalMiddleware())
    except (OperationBusy, BlockingIOError):
        raise InstallError('PlexConfigControl wykonuje inną operację. Spróbuj po jej zakończeniu.') from None
    except (OSError, subprocess.SubprocessError, sqlite3.Error, KeyError, TypeError, ValueError):
        raise InstallError('Nie można sprawdzić lub zaktualizować PlexConfigControl. Sprawdź stan w TrueNAS Apps.') from None
