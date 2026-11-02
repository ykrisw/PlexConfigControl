"""Atomic publication after archive verification and confirmed snapshot removal.

Caller holds the operation lock and passes a private verified source file.
A hidden staging file is confined to the destination and removed on failure.
"""
import hashlib
import os
import secrets
import stat
from .archive_store import NAME

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
        # link is atomic and fails if the final filename already exists.
        os.link(stage,name,src_dir_fd=directory,dst_dir_fd=directory,follow_symlinks=False)
        os.fsync(directory)
        os.unlink(stage,dir_fd=directory); created=False
        os.fsync(directory)
        return name
    finally:
        try:
            if created:
                os.unlink(stage,dir_fd=directory)
                os.fsync(directory)
        finally:
            os.close(directory)
