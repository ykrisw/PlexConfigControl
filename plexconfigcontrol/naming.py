"""Portable installation-selected output names; timestamps/extensions stay fixed."""
import re
from dataclasses import dataclass

DEFAULT_FOLDER = 'Plex Backup'
DEFAULT_PREFIX = 'PlexConfig'
PREFIX = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
ARCHIVE_PATTERN = r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}_\d{4}\.\d{2}\.\d{2}_\d{2}\.\d{2}\.\d{2}\.tar\.gz'
ARCHIVE_NAME = re.compile(ARCHIVE_PATTERN+r'\Z')


class InvalidNaming(ValueError):
    pass


def folder_component(value):
    if (not isinstance(value,str) or not 1<=len(value)<=80 or len(value.encode('utf-8'))>200
            or value!=value.strip() or value.endswith('.') or value in ('.','..')
            or any(ord(c)<32 or c in '/\\:<>"|?*' for c in value)):
        raise InvalidNaming('Invalid backup folder name')
    reserved={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
    if value.split('.')[0].upper() in reserved:
        raise InvalidNaming('Reserved backup folder name')
    return value


def archive_prefix(value):
    if not isinstance(value,str) or not PREFIX.fullmatch(value):
        raise InvalidNaming('Archive prefix must use 1–64 ASCII letters, digits, underscores or hyphens, starting with a letter or digit')
    return value


@dataclass(frozen=True)
class Naming:
    folder_name: str = DEFAULT_FOLDER
    archive_prefix: str = DEFAULT_PREFIX

    def __post_init__(self):
        folder_component(self.folder_name)
        archive_prefix(self.archive_prefix)

    @classmethod
    def from_input(cls, folder_name=None, prefix=None):
        return cls(DEFAULT_FOLDER if folder_name in (None,'') else folder_name,
                   DEFAULT_PREFIX if prefix in (None,'') else prefix)


def load_naming(state_directory):
    """Private iXVolume configuration; never infer names from archive contents."""
    import json
    import os
    import stat
    from pathlib import Path
    path=Path(state_directory)/'output-naming.json'
    try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:return Naming()
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>4096 or info.st_mode&0o077:
            raise InvalidNaming('Invalid private naming record')
        try:
            data=json.loads(stream.read(4097))
            if not isinstance(data,dict) or set(data)!={'folder_name','archive_prefix'}:raise ValueError()
            return Naming(**data)
        except (ValueError,TypeError):raise InvalidNaming('Invalid private naming record') from None


def save_naming(state_directory, naming):
    """First-install exclusive save; never silently replace an existing choice."""
    import json
    import os
    from pathlib import Path
    if not isinstance(naming,Naming):raise InvalidNaming('Validated naming required')
    root=Path(state_directory)
    if not root.is_dir() or root.is_symlink():raise InvalidNaming('Private installation state required')
    body=json.dumps({'folder_name':naming.folder_name,'archive_prefix':naming.archive_prefix},ensure_ascii=False).encode()
    try:fd=os.open(root/'output-naming.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:
        if load_naming(root)!=naming:raise InvalidNaming('Installation naming already differs')
        return
    with os.fdopen(fd,'wb') as stream:
        stream.write(body);stream.flush();os.fsync(stream.fileno())
    directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(directory)
    finally:os.close(directory)
