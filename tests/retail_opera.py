"""Locate an installed retail Opera; never substitute Chrome/Chromium."""
import os
import platform
import shutil
from pathlib import Path


def opera_binary():
    if platform.system()=='Darwin':
        candidates=[Path('/Applications/Opera.app/Contents/MacOS/Opera'),Path.home()/'Applications/Opera.app/Contents/MacOS/Opera']
    elif platform.system()=='Windows':
        candidates=[]
        for base in ('LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)'):
            if not os.environ.get(base):continue
            root=Path(os.environ[base])/'Programs'/'Opera' if base=='LOCALAPPDATA' else Path(os.environ[base])/'Opera'
            candidates.append(root/'opera.exe')
            if root.is_dir():
                versions=[p for p in root.iterdir() if p.is_dir() and all(part.isdecimal() for part in p.name.split('.'))]
                versions.sort(key=lambda p:tuple(int(part) for part in p.name.split('.')),reverse=True)
                candidates.extend(p/'opera.exe' for p in versions)
    else:
        candidates=[Path(value) for name in ('opera','opera-stable') if (value:=shutil.which(name))]
    for path in candidates:
        if path.is_file():return str(path)
    raise RuntimeError('Retail Opera is not installed; refusing to substitute another browser')
