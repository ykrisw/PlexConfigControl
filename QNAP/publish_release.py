"""Publish the verified platform packages into the common 1.6 release."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

TAG = 'v1.6'
TITLE = 'PlexConfigControl 1.6 — TrueNAS SCALE / QNAP QuTS hero'
NAMES = {'PlexConfigControl_TrueNAS_x86-64v1.6.zip', 'PlexConfigControl_QuTShero_x86-64v1.6.qpkg'}


def gh(*args, capture=True):
    return subprocess.run(['gh', *args], check=True, capture_output=capture, text=True).stdout


def publish(directory):
    repo = os.environ['GH_REPO']
    notes = Path(__file__).with_name('release-notes-1.6.md')
    try:
        gh('release', 'view', TAG)
    except subprocess.CalledProcessError:
        try:
            gh('release', 'create', TAG, '--draft', '--target', os.environ['GITHUB_SHA'],
               '--title', TITLE, '--notes-file', str(notes))
        except subprocess.CalledProcessError:
            # The other platform publisher may have created the same draft.
            gh('release', 'view', TAG)
    files = sorted(str(path) for path in Path(directory).iterdir()
                   if path.name in NAMES or path.name.startswith(('SHA256SUMS', 'qnap-repository'))
                   or path.name == 'PlexConfigControl_80.png')
    if not files:
        raise ValueError('No verified release files')
    gh('release', 'upload', TAG, *files, '--clobber')
    release = json.loads(gh('release', 'view', TAG, '--json', 'assets'))
    if not NAMES.issubset({asset['name'] for asset in release['assets']}):
        print('Platform files uploaded; waiting for the other verified installer.')
        return
    gh('release', 'edit', TAG, '--draft=false', '--latest', '--title', TITLE, '--notes-file', str(notes))
    # Retain previous releases as clearly labelled history; remove misleading 1.6 filenames there.
    try:
        previous = json.loads(gh('api', f'repos/{repo}/releases/tags/v1.0.5'))
    except subprocess.CalledProcessError:
        return
    aliases = {
        'PlexConfigControl_TrueNAS_x86-64v1.6.zip': ('PlexConfigControlTrueNAS_1.0.5.zip', 'SHA256SUMS'),
        'PlexConfigControl_QuTShero_x86-64v1.6.qpkg': ('PlexConfigControlQuTShero_1.0.5.qpkg', 'SHA256SUMS_QNAP'),
    }
    out = Path('historical-checksums')
    out.mkdir(exist_ok=True)
    body = previous['body'] or ''
    checksum_files = []
    for asset in previous['assets']:
        if asset['name'] in aliases:
            old = asset['name']
            name, checksum = aliases[old]
            gh('api', f"repos/{repo}/releases/assets/{asset['id']}", '--method', 'PATCH', '-f', 'name='+name)
            body = body.replace(old, name)
            digest = asset['digest'].removeprefix('sha256:')
            path = out/checksum
            path.write_text(digest+'  '+name+'\n')
            checksum_files.append(str(path))
    if checksum_files:
        gh('release', 'upload', 'v1.0.5', *checksum_files, '--clobber')
    marker = '**Superseded by [PlexConfigControl 1.6](https://github.com/ykrisw/PlexConfigControl/releases/tag/v1.6).**'
    if marker not in body:
        body = marker+'\n\n'+body
    note = out/'notes.md'
    note.write_text(body)
    gh('release', 'edit', 'v1.0.5', '--notes-file', str(note), '--latest=false')
    print('Both version 1.6 installers published; previous release marked as historical.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    publish(parser.parse_args().directory)
