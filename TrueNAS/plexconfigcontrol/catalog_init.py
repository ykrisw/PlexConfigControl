"""Initialize only the new iXVolume allocated by the Apps installer."""
import argparse
import fcntl
import os
from pathlib import Path

from .naming import Naming, load_naming, save_naming


STATE = Path('/var/lib/plexconfigcontrol')
UID = 568


def initialize(state, naming):
    state = Path(state)
    if state.resolve(strict=True) != state:
        raise ValueError('Invalid application state volume')
    fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if os.listdir(fd):
            info = os.fstat(fd)
            if (info.st_uid != UID or info.st_gid != UID or info.st_mode & 0o077
                    or load_naming(state) != naming or not (state/'output-naming.json').is_file()):
                raise ValueError('The existing state does not match the prepared installation')
            saved = os.stat('output-naming.json', dir_fd=fd, follow_symlinks=False)
            if saved.st_uid != UID or saved.st_gid != UID or saved.st_mode & 0o077:
                raise ValueError('The existing naming record is not owned by the application')
            return
        save_naming(state, naming)
        os.chown('output-naming.json', UID, UID, dir_fd=fd, follow_symlinks=False)
        os.fchmod(fd, 0o700)
        os.fchown(fd, UID, UID)
        os.fsync(fd)
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Initialize the managed PlexConfigControl iXVolume')
    parser.add_argument('--folder', required=True)
    parser.add_argument('--prefix', required=True)
    args = parser.parse_args(argv)
    try:
        os.umask(0o077)
        initialize(STATE, Naming(args.folder, args.prefix))
        return 0
    except Exception:
        print('PlexConfigControl could not initialize the managed state volume.', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
