"""Read-only checks for the native Plex runtime installed as a QNAP package."""
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .qnap_discovery import QnapDiscoveryError


@dataclass(frozen=True)
class QnapPlexRuntime:
    sqlite_executable: str
    sqlite_version: str
    service_script: str


def inspect_plex_runtime(installation, *, runner=subprocess.run,
                         resolve=None, executable=os.access):
    """Probe only an in-memory database; never execute the package service script.

    Resolve native tools inside the discovered package before invoking anything.
    The service script is recorded for a future scoped service adapter only.
    """
    resolve = resolve or (lambda path: str(Path(path).resolve(strict=True)))
    root = Path(installation.install_directory)

    def tool(path):
        try:
            resolved = Path(resolve(str(path)))
        except OSError:
            raise QnapDiscoveryError('QNAP_PLEX_TOOL_UNAVAILABLE') from None
        if resolved.parent != root or not executable(str(resolved), os.X_OK):
            raise QnapDiscoveryError('QNAP_PLEX_TOOL_OUTSIDE_PACKAGE_OR_NOT_EXECUTABLE')
        return str(resolved)

    sqlite = tool(root / 'Plex SQLite')
    try:
        setting = runner(['/sbin/getcfg', 'PlexMediaServer', 'Shell', '-f',
                          '/etc/config/qpkg.conf'], capture_output=True,
                         text=True, timeout=15, check=False)
        if setting.returncode != 0:
            raise QnapDiscoveryError('QNAP_PLEX_SERVICE_UNAVAILABLE')
        if setting.stdout.strip() != str(root / 'plex.sh'):
            raise QnapDiscoveryError('QNAP_PLEX_SERVICE_LOCATION_CHANGED')
        service = tool(root / 'plex.sh')
        result = runner([sqlite, '-batch', '-init', '/dev/null', ':memory:',
                         'SELECT sqlite_version(); PRAGMA integrity_check;'],
                        capture_output=True, text=True, timeout=15, check=False,
                        env={**os.environ, 'SQLITE_HISTORY': '/dev/null'})
    except (OSError, subprocess.SubprocessError):
        raise QnapDiscoveryError('QNAP_PLEX_RUNTIME_UNAVAILABLE') from None
    lines = result.stdout.strip().splitlines()
    if (result.returncode != 0 or len(lines) != 2 or lines[1] != 'ok'
            or not re.fullmatch(r'\d+\.\d+\.\d+', lines[0])):
        raise QnapDiscoveryError('QNAP_PLEX_SQLITE_SELF_TEST_FAILED')
    return QnapPlexRuntime(sqlite, lines[0], service)


def plex_process_state(installation, *, proc=Path('/proc'), readlink=os.readlink):
    """Match the main executable, without reading arguments or environment.

    Enable=TRUE in qpkg.conf is not proof of a running service. Inaccessible
    processes make a negative result unknown rather than falsely stopped.
    """
    expected = str(Path(installation.install_directory) / 'Plex Media Server')
    incomplete = False
    try:
        entries = list(proc.iterdir())
    except OSError:
        return 'UNKNOWN'
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            target = readlink(entry / 'exe')
        except (FileNotFoundError, ProcessLookupError):
            continue  # A process can exit during the scan.
        except OSError:
            incomplete = True
            continue
        # A deleted executable may still be running after a package update.
        if target in (expected, expected + ' (deleted)'):
            return 'RUNNING'
    return 'UNKNOWN' if incomplete else 'STOPPED'
