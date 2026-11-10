"""Atomic publication after archive verification and confirmed snapshot removal.

Caller holds the operation lock and passes a private verified source file.
A hidden staging file is confined to the destination and removed on failure.
"""
import hashlib
import os
import secrets
import stat
from .archive_store import NAME, ArchiveStore, ArchiveChanged, file_identity

class PublishError(RuntimeError):
    pass

def publish_new(source,destination,name,expected_sha256,staging_callback):
    if not isinstance(name,str) or not NAME.fullmatch(name):
        raise ValueError('Invalid archive name')
    if len(expected_sha256)!=64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError('Invalid verification digest')
    directory=os.open(destination,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    stage='.pcc-'+secrets.token_hex(16)+'.tmp'
    created=False
    try:
        staging_callback(stage)  # Must commit to ixVolume before file creation.
        fd=os.open(stage,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o666,dir_fd=directory)
        created=True
        digest=hashlib.sha256()
        with os.fdopen(fd,'wb') as output:
            input_fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(input_fd,'rb') as input_file:
                if not stat.S_ISREG(os.fstat(input_file.fileno()).st_mode):
                    raise PublishError('Verified source must be a regular file')
                while chunk:=input_file.read(1024*1024):
                    digest.update(chunk); output.write(chunk)
            output.flush(); os.fsync(output.fileno())
            if digest.hexdigest()!=expected_sha256:
                raise PublishError('Source changed since verification')
            # Keep the verified inode open through publication so a replaced
            # destination path cannot be recorded as the verified archive.
            os.link(stage,name,src_dir_fd=directory,dst_dir_fd=directory,follow_symlinks=False)
            os.fsync(directory)
            os.unlink(stage,dir_fd=directory); created=False
            os.fsync(directory)
            return file_identity(os.fstat(output.fileno()))
    finally:
        try:
            if created:
                os.unlink(stage,dir_fd=directory)
                os.fsync(directory)
        finally:
            os.close(directory)


def capture_original(destination, selected):
    """Bind the user's selection to its current change time before backup starts."""
    directory = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        ArchiveStore._verify(directory, selected)
        info = os.stat(selected.name, dir_fd=directory, follow_symlinks=False)
        # Verify again: do not bind a file substituted between the two reads.
        ArchiveStore._verify(directory, selected)
        return file_identity(info)
    finally:
        os.close(directory)


def retire_original(destination, selected, original_identity, new_name, expected_digest):
    """Re-read the published bytes before removing the explicitly selected old copy.

    The app's operation lock excludes app writers. External SMB writers must not
    modify either archive during replacement: stat/unlink is not a filesystem
    compare-and-swap. Detected external changes retain both files for review.
    """
    if not NAME.fullmatch(new_name) or new_name == selected.name:
        raise ValueError('Replacement needs a new dated filename')
    directory = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(new_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        with os.fdopen(fd, 'rb') as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise PublishError('Published archive is not a regular file')
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
            if (digest != expected_digest or file_identity(before) !=
                    file_identity(os.fstat(source.fileno()))):
                raise PublishError('Published archive failed verification')
            ArchiveStore._verify(directory, selected)
            if file_identity(os.stat(selected.name, dir_fd=directory,
                                     follow_symlinks=False)) != original_identity:
                raise ArchiveChanged('Original archive changed during backup')
            final = os.stat(new_name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(final.st_mode) or file_identity(final) != file_identity(before):
                raise ArchiveChanged('Published archive changed during backup')
            os.unlink(selected.name, dir_fd=directory)
            os.fsync(directory)
    finally:
        os.close(directory)
