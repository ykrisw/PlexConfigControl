"""Expose only the exact recorded snapshot below a configured Plex mount."""
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path

class SnapshotReadError(RuntimeError):
    pass

class SnapshotReader:
    def __init__(self,config_mount,dataset,expected_device,expected_inode,api):
        self.mount=Path(config_mount)
        self.dataset=dataset
        self.identity=(expected_device,expected_inode)
        self.api=api

    @contextmanager
    def __call__(self,identifier):
        prefix=self.dataset+'@'
        if not isinstance(identifier,str) or not identifier.startswith(prefix):
            raise SnapshotReadError('Snapshot is outside configured dataset')
        name=identifier[len(prefix):]
        if not re.fullmatch(r'pcc-(backup|restore)-[0-9a-f]{32}',name):
            raise SnapshotReadError('Invalid application snapshot identity')
        if not self.mount.is_absolute() or self.mount.resolve()!=self.mount:
            raise SnapshotReadError('Unsafe configuration mount')
        info=self.mount.lstat()
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev,info.st_ino)!=self.identity:
            raise SnapshotReadError('Configuration mount identity changed')
        rows=self.api.call('pool.snapshot.query',[['id','=',identifier]])
        if not isinstance(rows,list) or len(rows)!=1 or rows[0].get('id')!=identifier:
            raise SnapshotReadError('Snapshot existence was not confirmed')
        flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
        handles=[]
        try:
            fd=os.open(self.mount,flags); handles.append(fd)
            for part in ('.zfs','snapshot',name):
                fd=os.open(part,flags,dir_fd=fd); handles.append(fd)
            # Holding a directory fd stabilizes access against path replacement.
            # It also must be closed before snapshot deletion can be attempted.
            snapshot=Path('/proc/self/fd')/str(fd)
            if not os.statvfs(fd).f_flag & os.ST_RDONLY:
                raise SnapshotReadError('Snapshot filesystem is not read-only')
            yield self.mount / '.zfs' / 'snapshot' / name
        except OSError as error:
            raise SnapshotReadError('Snapshot contents are inaccessible') from error
        finally:
            for fd in reversed(handles): os.close(fd)
