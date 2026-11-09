"""Entry point for the isolated execution owner in a trusted deployment."""
import argparse
import fcntl
import os
import signal
import shutil
import stat
from contextlib import contextmanager
from pathlib import Path

from .connection_check import read_secret
from .database_check import probe_sqlite
from .execution_ipc import ExecutionSocketServer
from .plex_storage import discover_plex_storage
from .production_execution import ExecutionStorage, build_execution_worker
from .transport import build_client


@contextmanager
def _socket_ownership(path):
    parent = path.parent
    owner = os.geteuid()
    if not path.is_absolute() or parent.resolve(strict=True) != parent:
        raise ValueError('Invalid execution socket directory')
    info = parent.stat()
    if info.st_uid != owner or info.st_mode & 0o022:
        raise ValueError('Execution socket directory must belong to the worker')
    lock = path.with_name(path.name + '.lock')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_mode & 0o077:
            raise ValueError('Invalid execution socket lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            info = path.lstat()
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != owner:
                raise ValueError('Execution socket path is already in use')
            path.unlink()
        yield
    finally:
        os.close(fd)


def serve(worker, socket_path, panel_uid):
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    with _socket_ownership(socket_path):
        worker.reconcile_startup()
        previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            with ExecutionSocketServer(socket_path, worker, panel_uid) as server:
                socket_info = socket_path.lstat()
                server.timeout = 1
                try:
                    while not stopping:
                        server.handle_request()
                finally:
                    try:
                        current = socket_path.lstat()
                        if (current.st_dev, current.st_ino) == (socket_info.st_dev, socket_info.st_ino):
                            socket_path.unlink()
                    except FileNotFoundError:
                        pass
        finally:
            worker.close()
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def _verify_process():
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines()
                  if ':' in line)
    required = (1 << 0) | (1 << 1) | (1 << 3) | (1 << 4)  # CHOWN, DAC_OVERRIDE, FOWNER, FSETID.
    if int(status['CapEff'].strip(), 16) != required or status['NoNewPrivs'].strip() != '1':
        raise ValueError('Worker did not receive exactly the expected file capabilities')
    if shutil.which('rsync') is None or shutil.which('tar') is None:
        raise ValueError('Worker archive tools are unavailable')


def main(argv=None):
    parser = argparse.ArgumentParser(description='PlexConfigControl execution owner')
    for option in ('state', 'archives', 'config-mount', 'host-config', 'dataset', 'socket',
                   'truenas-url', 'api-username', 'api-key-file', 'plex-sqlite', 'sqlite-version'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--ca-file')
    parser.add_argument('--panel-uid', required=True, type=int)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        # The socket and private state are shared with the same UID in the
        # separate unprivileged web environment. Credentials are worker-only.
        if args.panel_uid != os.geteuid() or args.panel_uid <= 0:
            raise ValueError('The worker and panel must use the configured non-root UID')
        _verify_process()
        api = build_client(args.truenas_url, args.api_username, read_secret(args.api_key_file),
                           args.ca_file, timeout=10)
        plan = discover_plex_storage(api, manual_source=args.host_config)
        if plan.dataset != args.dataset:
            raise ValueError('Configured Plex dataset no longer matches TrueNAS')
        storage = ExecutionStorage(api, plan, args.config_mount, args.state, args.archives)
        probe_sqlite(args.plex_sqlite, args.sqlite_version)
        worker = build_execution_worker(storage, sqlite_executable=args.plex_sqlite,
                                        sqlite_version=args.sqlite_version)
        serve(worker, Path(args.socket), args.panel_uid)
        return 0
    except Exception:
        print('PlexConfigControl execution owner could not start. Check the worker configuration.', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
