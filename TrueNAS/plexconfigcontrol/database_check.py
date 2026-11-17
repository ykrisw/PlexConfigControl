"""SQLite integrity checks on private restore staging, never live Plex files.

Use the SQLite executable shipped with the matching Plex version when required
by Plex's database extensions. Stock sqlite3 is not assumed compatible.
"""
import os
import stat
import subprocess
import re
from pathlib import Path

DATABASES=('com.plexapp.plugins.library.db','com.plexapp.plugins.library.blobs.db')

class DatabaseCheckError(RuntimeError):
    pass

def probe_sqlite(sqlite_executable, expected_version, *, timeout=15, runner=subprocess.run):
    """Test the packaged executable on an in-memory DB, never the live library.

    A passing probe establishes availability and the configured SQLite version;
    Plex extension compatibility still requires real staged-database checks.
    The expected version comes from application packaging, not browser input.
    """
    executable=Path(sqlite_executable)
    if not executable.is_absolute() or not re.fullmatch(r'\d+\.\d+\.\d+',expected_version):
        raise DatabaseCheckError('Invalid packaged database-checker configuration')
    try:
        result=runner([str(executable),':memory:',
                       'SELECT sqlite_version(); PRAGMA integrity_check;'],
                      capture_output=True,text=True,timeout=timeout,
                      env={**os.environ,'SQLITE_HISTORY':'/dev/null'})
    except (OSError,subprocess.TimeoutExpired) as error:
        raise DatabaseCheckError('Packaged database checker is unavailable') from error
    lines=result.stdout.strip().splitlines()
    if result.returncode!=0 or lines!=[expected_version,'ok']:
        raise DatabaseCheckError('Packaged database checker failed its version or integrity self-test')
    return expected_version

class PlexDatabaseChecker:
    """Restore adapter: preflight must pass before any staged DB is opened."""
    def __init__(self, executable, expected_version, *, runner=subprocess.run):
        self.executable=executable
        self.expected_version=expected_version
        self.runner=runner

    def __call__(self, staging_config):
        probe_sqlite(self.executable,self.expected_version,runner=self.runner)
        return check_databases(staging_config,self.executable,runner=self.runner)

def check_databases(staging_config, sqlite_executable, *, timeout=600, runner=subprocess.run):
    root=Path(staging_config)
    directory=root/'Library'/'Application Support'/'Plex Media Server'/'Plug-in Support'/'Databases'
    # All staging ancestors must be real directories, not archive-provided links.
    current=root
    for part in ('','Library','Application Support','Plex Media Server','Plug-in Support','Databases'):
        if part: current=current/part
        info=current.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise DatabaseCheckError('Unsafe staging database directory')
    results=[]
    for name in DATABASES:
        path=directory/name
        try:
            info=path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size==0:
                raise DatabaseCheckError('Missing or invalid staged database: '+name)
            # Opening staged DB may perform WAL recovery. That is intentional;
            # source archive and live configuration are never opened here.
            result=runner([str(sqlite_executable),str(path),'PRAGMA integrity_check;'],
                          capture_output=True,text=True,timeout=timeout,
                          env={**os.environ,'SQLITE_HISTORY':'/dev/null'})
        except (OSError,subprocess.TimeoutExpired) as error:
            raise DatabaseCheckError('Database integrity check could not complete: '+name) from error
        if result.returncode!=0 or result.stdout.strip()!='ok':
            raise DatabaseCheckError('Database integrity check failed: '+name)
        results.append(name)
    return results
