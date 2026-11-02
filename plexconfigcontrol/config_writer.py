"""Scoped rsync writer for a preconfigured existing Plex dataset mountpoint.

Mount provenance must be checked by deployment integration. Never auto-detect
or adopt a target from a browser request. Requires GNU rsync and appropriate
file ownership/ACL capabilities inside the application container.
"""
import os
import stat
import subprocess
from pathlib import Path

class ConfigWriteError(RuntimeError):
    pass

class ConfigWriter:
    def __init__(self,target,expected_device,expected_inode,plex_status,*,runner=subprocess.run):
        self.target=Path(target)
        self.identity=(expected_device,expected_inode)
        self.plex_status=plex_status
        self.runner=runner
        self._check_target()

    def _check_target(self):
        if not self.target.is_absolute() or self.target==Path('/'):
            raise ConfigWriteError('Invalid configured target')
        info=self.target.lstat()
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev,info.st_ino)!=self.identity:
            raise ConfigWriteError('Plex configuration directory identity changed')
        if self.target.resolve()!=self.target:
            raise ConfigWriteError('Target path contains symbolic links')
        if self.plex_status.read()['state']!='STOPPED':
            raise ConfigWriteError('Plex is not confirmed STOPPED')

    def _source(self,source):
        source=Path(source)
        if not source.is_absolute() or source.resolve()!=source or not source.is_dir():
            raise ConfigWriteError('Unsafe staged configuration')
        if source==self.target or source in self.target.parents or self.target in source.parents:
            raise ConfigWriteError('Source and target overlap')
        return source

    def write(self,source):
        source=self._source(source)
        self._check_target()
        result=self.runner(['rsync','-aHAXS','--numeric-ids','--one-file-system',
                            '--delete-delay','--',str(source)+'/',str(self.target)+'/'],
                           stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        if result.returncode:
            raise ConfigWriteError('Configuration synchronization failed')
        self._check_target()

    def verify(self,source):
        source=self._source(source)
        self._check_target()
        result=self.runner(['rsync','-aHAXS','--numeric-ids','--one-file-system',
                            '--delete','--dry-run','--checksum','--itemize-changes',
                            '--',str(source)+'/',str(self.target)+'/'],
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if result.returncode or result.stdout.strip():
            raise ConfigWriteError('Restored files or metadata do not match staging')
        return True
