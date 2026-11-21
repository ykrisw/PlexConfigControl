"""Publish the independently verified TrueNAS maintenance installer; retain 1.6."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

TAG='v1.6.1'
TITLE='PlexConfigControl 1.6.1 — TrueNAS SCALE certificate recovery'
NAME='PlexConfigControl_TrueNAS_x86-64v1.6.1.zip'


def gh(*args):
    return subprocess.check_output(['gh',*args],text=True)


def publish(directory):
    directory=Path(directory)
    package=directory/NAME;checksum=hashlib.sha256(package.read_bytes()).hexdigest()
    if (directory/'SHA256SUMS').read_text().strip()!=checksum+'  '+NAME:
        raise ValueError('Installer checksum does not match the verified package')
    notes=Path(__file__).with_name('release-notes-1.6.1.md')
    try:gh('release','view',TAG)
    except subprocess.CalledProcessError:
        gh('release','create',TAG,'--draft','--target',os.environ['GITHUB_SHA'],'--title',TITLE,'--notes-file',str(notes))
    gh('release','upload',TAG,str(package),str(directory/'SHA256SUMS'),'--clobber')
    with tempfile.TemporaryDirectory() as folder:
        gh('release','download',TAG,'--pattern',NAME,'--dir',folder)
        if hashlib.sha256(Path(folder,NAME).read_bytes()).hexdigest()!=checksum:
            raise ValueError('Published installer verification failed; release remains draft')
    gh('release','edit',TAG,'--draft=false','--latest','--title',TITLE,'--notes-file',str(notes))
    print('TrueNAS 1.6.1 published and downloaded checksum verified. Version 1.6 assets unchanged.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path)
    publish(parser.parse_args().directory)
