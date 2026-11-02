"""Private restore staging with no writes to live Plex configuration."""
import os
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from .archives import validate_archive

class StagingError(RuntimeError):
    pass

@contextmanager
def stage_archive(archive_path,state_directory,expected_sha256,*,runner=subprocess.run):
    """Copy archive privately, validate identity, then extract with GNU tar.

    Links, special files, duplicate paths and traversal are rejected by the
    validator before extraction. Private copy prevents later SMB replacement
    from changing extraction input. ACL/xattrs are retained by GNU tar.
    """
    state=Path(state_directory)
    if not state.is_dir():
        raise StagingError('Application state directory is unavailable')
    with tempfile.TemporaryDirectory(prefix='restore-',dir=state) as workspace:
        workspace=Path(workspace)
        private=workspace/'source.tar.gz'
        fd=os.open(archive_path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise StagingError('Archive must be a regular file')
            # Workspace is private (0700); source copy is never user-accessible.
            with private.open('xb') as output:
                shutil.copyfileobj(source,output,length=1024*1024)
                output.flush(); os.fsync(output.fileno())
        result=validate_archive(private)
        if result.sha256!=expected_sha256:
            raise StagingError('Archive changed since selection was validated')
        destination=workspace/'extracted'; destination.mkdir(mode=0o700)
        extracted=runner(['tar','--acls','--xattrs','--numeric-owner','--same-owner',
                          '--same-permissions','-xzpf',str(private),'-C',str(destination)],
                         stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        if extracted.returncode:
            raise StagingError('Archive extraction failed')
        config=destination/'config'
        if not config.is_dir() or config.is_symlink():
            raise StagingError('Extracted configuration is missing')
        yield config
