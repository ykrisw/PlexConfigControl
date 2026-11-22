"""Publish independently verified QNAP maintenance builds without changing TrueNAS."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
TAG='qnap-v1.6.3'
NAME='PlexConfigControl_QuTShero_x86-64v1.6.3.qpkg'
def gh(*args):return subprocess.check_output(['gh',*args],text=True)
def publish(directory):
    folder=Path(directory);package=folder/NAME;checksum=hashlib.sha256(package.read_bytes()).hexdigest()
    if (folder/'SHA256SUMS_QNAP').read_text().strip()!=checksum+'  '+NAME:raise ValueError('QNAP checksum mismatch')
    notes=Path(__file__).with_name('release-notes-1.6.3.md')
    try:gh('release','view',TAG)
    except subprocess.CalledProcessError:gh('release','create',TAG,'--draft','--target',os.environ['GITHUB_SHA'],'--title','PlexConfigControl 1.6.3 — QNAP QuTS hero x86-64','--notes-file',str(notes))
    gh('release','upload',TAG,*(str(folder/name) for name in (NAME,'SHA256SUMS_QNAP','qnap-repository.xml','qnap-repository-pl.xml','PlexConfigControl_80.png')),'--clobber')
    with tempfile.TemporaryDirectory() as temporary:
        gh('release','download',TAG,'--pattern',NAME,'--dir',temporary)
        if hashlib.sha256((Path(temporary)/NAME).read_bytes()).hexdigest()!=checksum:raise ValueError('Uploaded QNAP checksum mismatch')
    gh('release','edit',TAG,'--draft=false','--latest','--notes-file',str(notes))
    print('QNAP 1.6.3 published and downloaded checksum verified; TrueNAS unchanged.')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);publish(parser.parse_args().directory)
