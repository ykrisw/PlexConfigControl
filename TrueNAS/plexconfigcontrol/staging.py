"""Private restore staging with no writes to live Plex configuration."""
import os
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from .archives import validate_archive

class StagingError(RuntimeError):
    pass

@contextmanager
def stage_archive(archive_path,state_directory,expected_sha256,*,runner=subprocess.run,progress_callback=None):
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
            info=os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise StagingError('Archive must be a regular file')
            total=info.st_size or None
            if progress_callback:
                progress_callback('STAGING_ARCHIVE',0,total)
            # Workspace is private (0700); source copy is never user-accessible.
            with private.open('xb') as output:
                done=reported=0
                while chunk:=source.read(1024*1024):
                    output.write(chunk)
                    done+=len(chunk)
                    if done>info.st_size:
                        raise StagingError('Archive changed since selection was validated')
                    if progress_callback and done<info.st_size and done-reported>=16*1024*1024:
                        progress_callback('STAGING_ARCHIVE',done,total)
                        reported=done
                if done!=info.st_size:
                    raise StagingError('Archive changed since selection was validated')
                output.flush(); os.fsync(output.fileno())
            if progress_callback:
                progress_callback('STAGING_ARCHIVE',done,total)
                progress_callback('PREPARING')
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
