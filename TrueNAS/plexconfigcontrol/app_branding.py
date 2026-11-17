"""Update this custom app's version and icon without changing its Compose config."""
import base64
import os
from pathlib import Path
import stat
import tempfile
import re
import shutil
from . import __version__ as VERSION

APP = 'plexconfigcontrol'
METADATA = Path('/mnt/.ix-apps/app_configs') / APP / 'metadata.yaml'
LOGO = Path(__file__).with_name('static') / 'pcc-logo.svg'


def _prepare_version(path, previous, icon):
    if not isinstance(previous, str) or not re.fullmatch(r'\d+(?:\.\d+){1,3}', previous):
        raise ValueError('Unexpected custom application version')
    versions = path.parent / 'versions'
    source, target = versions / previous, versions / VERSION
    if versions.resolve(strict=True) != versions or source.resolve(strict=True) != source:
        raise ValueError('Unexpected application version path')
    if target.is_symlink() or versions.stat().st_uid != os.geteuid() or versions.stat().st_mode & 0o022:
        raise ValueError('Unexpected application version directory permissions')
    required = ('user_config.yaml', 'templates/rendered/docker-compose.yaml', 'app.yaml')
    for entry in [source, *source.rglob('*')]:
        info = entry.lstat()
        if info.st_uid != os.geteuid() or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError('Unexpected application version tree identity')
    if any(not (source / name).is_file() for name in required):
        raise ValueError('Application version configuration is incomplete')
    if source != target and not target.exists():
        temporary = Path(tempfile.mkdtemp(prefix='.pcc-version-', dir=versions))
        try:
            shutil.copytree(source, temporary, dirs_exist_ok=True)
            for entry in temporary.rglob('*'):
                if entry.is_file():
                    with entry.open('rb') as stream:
                        os.fsync(stream.fileno())
            for directory in [*sorted((p for p in temporary.rglob('*') if p.is_dir()), key=lambda p:len(p.parts), reverse=True), temporary]:
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            os.rename(temporary, target)
            fd = os.open(versions, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    if target.resolve(strict=True) != target:
        raise ValueError('Unexpected target version symlink')
    for name in required[:2]:
        candidate = target / name
        if candidate.resolve(strict=True) != candidate or candidate.read_bytes() != (source / name).read_bytes():
            raise ValueError('Target version differs from the current application configuration')
    import yaml
    app_yaml = target / 'app.yaml'
    if app_yaml.resolve(strict=True) != app_yaml:
        raise ValueError('Unexpected app metadata symlink')
    info = app_yaml.stat()
    value = yaml.safe_load(app_yaml.read_bytes())
    if not isinstance(value, dict):
        raise ValueError('Unexpected app version metadata')
    value.update(version=VERSION, app_version=VERSION, icon=icon)
    _replace(app_yaml, yaml.safe_dump(value, allow_unicode=True, sort_keys=False).encode(), info)


def _replace(path, data, info):
    fd, temporary = tempfile.mkstemp(prefix='.pcc-icon-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
            os.fchown(stream.fileno(), info.st_uid, info.st_gid)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install_icon(regenerate):
    """Preserve metadata, permissions and other apps; revert on regeneration error."""
    import yaml  # Supplied by the TrueNAS host; this does not run in the web panel.
    path = METADATA
    if path.resolve(strict=True) != path:
        raise ValueError('Unexpected application metadata symlink')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_size > 1048576:
            raise ValueError('Unexpected application metadata identity')
        before = stream.read()
    document = yaml.safe_load(before)
    if (not isinstance(document, dict) or document.get('custom_app') is not True
            or not isinstance(document.get('metadata'), dict)):
        raise ValueError('Expected this custom application metadata')
    icon = 'data:image/svg+xml;base64,' + base64.b64encode(LOGO.read_bytes()).decode('ascii')
    if (document['metadata'].get('icon') == icon and document.get('version') == VERSION
            and document.get('human_version') == VERSION and document['metadata'].get('app_version') == VERSION):
        regenerate()
        return
    _prepare_version(path, document.get('version'), icon)
    document['metadata']['icon'] = icon
    document['metadata']['version'] = VERSION
    document['metadata']['app_version'] = VERSION
    document['version'] = document['human_version'] = VERSION
    after = yaml.safe_dump(document, allow_unicode=True, sort_keys=False).encode()
    if path.read_bytes() != before or path.stat().st_ino != info.st_ino:
        raise ValueError('Application metadata changed during icon update')
    _replace(path, after, info)
    try:
        regenerate()
    except Exception:
        if path.read_bytes() == after:
            _replace(path, before, info)
            try:
                regenerate()
            except Exception:
                pass
        raise
