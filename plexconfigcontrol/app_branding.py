"""Set only this custom app's icon in TrueNAS 25.10 Apps metadata."""
import base64
import os
from pathlib import Path
import stat
import tempfile

APP = 'plexconfigcontrol'
METADATA = Path('/mnt/.ix-apps/app_configs') / APP / 'metadata.yaml'
LOGO = Path(__file__).with_name('static') / 'pcc-logo.svg'


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
    if document['metadata'].get('icon') == icon:
        return
    document['metadata']['icon'] = icon
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
