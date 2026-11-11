"""Archive creation from a coordinator-verified immutable snapshot directory.

Caller holds the operation lock and proves snapshot ownership/read-only identity.
This module never reads the live config, publishes an archive or removes snapshots.
GNU tar preserves numeric owners, ACLs and extended attributes.
"""
import os
import subprocess
import tarfile
from pathlib import Path
from .archives import validate_archive

class BackupArchiveError(RuntimeError):
    pass

def _archive_root(source_layout):
    if source_layout == 'config':
        return 'config'
    if source_layout == 'plex-data':
        # Native QNAP packages expose the Plex data directory itself, whereas
        # the portable archive/staging format includes these ancestors.
        return 'config/Library/Application Support/Plex Media Server'
    raise BackupArchiveError('Unsupported snapshot source layout')


def create_archive(snapshot_directory, output, *, tar_runner=subprocess.run, verification_progress=None,
                   source_layout='config', tar_executable='tar'):
    archive_root = _archive_root(source_layout)
    snapshot=Path(snapshot_directory)
    output=Path(output)
    if not snapshot.is_dir():
        raise BackupArchiveError('Snapshot directory is unavailable')
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb') as stream:
            result=tar_runner([
                os.fspath(tar_executable),'--acls','--xattrs','--numeric-owner','--format=pax',
                '--transform=s,^\\.,'+archive_root+',','-czpf','-',
                '-C',str(snapshot),'.',
            ],stdout=stream,stderr=subprocess.PIPE)
            stream.flush(); os.fsync(stream.fileno())
        if result.returncode:
            raise BackupArchiveError('Archive creation failed')
        if verification_progress:
            verification_progress(0, None)
        validation=validate_archive(output)
        compare_contents(snapshot,output,total_bytes=validation.bytes_read,
                         progress_callback=verification_progress,source_layout=source_layout)
        return validation
    except BaseException:
        # Only the exclusively-created output belongs to this call. Coordinator
        # must use a private workspace inaccessible to SMB or other writers.
        output.unlink(missing_ok=True)
        raise

def compare_contents(snapshot_directory, archive_path, *, total_bytes=None, progress_callback=None,
                     source_layout='config'):
    """Compare complete regular file coverage and byte contents to snapshot."""
    snapshot=Path(snapshot_directory)
    prefix = _archive_root(source_layout)+'/'
    expected=set()
    for directory,dirs,files in os.walk(snapshot,followlinks=False):
        for name in dirs:
            if (Path(directory)/name).is_symlink():
                raise BackupArchiveError('Directory symlinks unsupported')
        for name in files:
            path=Path(directory)/name
            if path.is_symlink() or not path.is_file():
                raise BackupArchiveError('Special files and symlinks unsupported')
            expected.add(path.relative_to(snapshot).as_posix())
    observed=set()
    done=reported=0
    if progress_callback and total_bytes:
        progress_callback(0,total_bytes)
    with tarfile.open(archive_path,'r:gz') as archive:
        for member in archive:
            if not member.isreg(): continue
            if not member.name.startswith(prefix):
                raise BackupArchiveError('Unexpected archive root')
            relative=member.name[len(prefix):]
            if relative not in expected or relative in observed:
                raise BackupArchiveError('Archive coverage mismatch')
            observed.add(relative)
            path=snapshot/relative
            if path.stat().st_size!=member.size:
                raise BackupArchiveError('Snapshot file size mismatch')
            with path.open('rb') as source, archive.extractfile(member) as entry:
                while chunk := entry.read(1024*1024):
                    if source.read(len(chunk)) != chunk:
                        raise BackupArchiveError('Snapshot content mismatch')
                    done+=len(chunk)
                    if progress_callback and total_bytes and done<total_bytes and done-reported>=16*1024*1024:
                        progress_callback(done,total_bytes)
                        reported=done
                if source.read(1):
                    raise BackupArchiveError('Snapshot content mismatch')
    if observed!=expected:
        raise BackupArchiveError('Archive is missing snapshot files')
    if total_bytes is not None and done!=total_bytes:
        raise BackupArchiveError('Verified byte count differs from archive validation')
    if progress_callback and total_bytes:
        progress_callback(done,total_bytes)
