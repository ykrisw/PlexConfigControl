"""Build one bilingual desktop installer ZIP from a committed source tree."""
import argparse
import hashlib
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from build_self_extracting import LAUNCHER, build


ROOT = 'PlexConfigControl_RC_Install'
RUNTIME_FILES = (
    '.dockerignore', 'Dockerfile', 'Dockerfile.worker', 'LICENSE', 'pyproject.toml',
    'deploy/install.sh', 'deploy/install_pl.py', 'deploy/installation-settings.example.json',
    'design/truenas-installation/initialize-plex-sqlite.sh',
    'design/truenas-installation/questions.yaml',
    'design/truenas-installation/templates/docker-compose.yaml',
)
SHORTCUTS = (
    'PlexConfigControl_Windows.cmd', 'PlexConfigControl_macOS.command',
    'PlexConfigControl_Linux.desktop',
)
RELEASE_NAME = 'PlexConfigControl_Installer_Windows_macOS_Linux_PL_EN.zip'
TRANSLATED_RUNTIME = {
    'deploy/install.sh', 'deploy/install_pl.py', 'plexconfigcontrol/host_install.py',
    'plexconfigcontrol/host_update.py',
}


def git(*args):
    return subprocess.check_output(['git', *args])


def write_zip(path, files):
    with ZipFile(path, 'w') as archive:
        for name, (content, mode) in sorted(files.items()):
            entry = ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = (0o100000 | mode) << 16
            archive.writestr(entry, content, compress_type=ZIP_DEFLATED, compresslevel=9)


def release(commit, output):
    tree = git('rev-parse', f'{commit}^{{tree}}').decode().strip()
    tracked = git('ls-tree', '-r', '--name-only', '-z', commit, '--', 'plexconfigcontrol')
    runtime = RUNTIME_FILES + tuple(path.decode() for path in tracked.split(b'\0') if path)

    def read(path):
        return git('show', f'{commit}:{path}')

    catalog = dict(line.split('\t', 1) for line in read('deploy/installer-en.tsv').decode().splitlines())
    translations = re.compile('|'.join(map(re.escape, sorted(catalog, key=len, reverse=True))))

    def english(text):
        return translations.sub(lambda match: catalog[match[0]], text)

    source_files = {path: (read(path), 0o644) for path in runtime}
    output.mkdir(parents=True, exist_ok=True)
    outer = {path: (read(path), 0o644) for path in ('INSTALL-EN.md', 'INSTRUKCJA-PL.md', 'LICENSE')}
    for lang in ('pl', 'en'):
        en = lang == 'en'
        entry = 'INSTALL.sh' if en else 'INSTALUJ.sh'
        launcher = 'PlexConfigControl_Installer.py' if en else 'PlexConfigControl_Instalator.py'
        guide = 'INSTALL-EN.md' if en else 'INSTRUKCJA-PL.md'
        files = source_files.copy()
        if en:
            for name in TRANSLATED_RUNTIME:
                files[name] = (english(files[name][0].decode()).encode(), 0o644)
        usage = 'Run:' if en else 'Uruchom:'
        entry_script = (
            '#!/bin/sh\nset -eu\n'
            f'[ "$(id -u)" -eq 0 ] || {{ printf \'%s\\n\' \'{usage} sudo sh {entry}\' >&2; exit 1; }}\n'
            'cd "$(dirname "$0")"\nexec python3 -m deploy.install_pl "$@"\n'
        )
        files[entry] = (entry_script.encode(), 0o755)
        files[guide] = (read(guide), 0o644)
        files['BUILD-INFO.txt'] = (f'PlexConfigControl 1.0.10\nSource tree before packaging: {tree}\n'.encode(), 0o644)
        checksums = ''.join(f'{hashlib.sha256(content).hexdigest()}  {name}\n'
                            for name, (content, _) in sorted(files.items()))
        files['SHA256SUMS'] = (checksums.encode(), 0o644)
        with TemporaryDirectory() as temporary:
            work = Path(temporary)
            inner = work / 'payload.zip'
            write_zip(inner, {f'{ROOT}/{name}': item for name, item in files.items()})
            build(inner, work / launcher, entry_point=f'{ROOT}/{entry}',
                  launcher=english(LAUNCHER) if en else LAUNCHER)
            outer[launcher] = ((work / launcher).read_bytes(), 0o644)
    for name in SHORTCUTS:
        script = read(f'deploy/{name}').decode()
        if name.endswith('.cmd'):
            script = script.replace('\r\n', '\n').replace('\n', '\r\n')
        outer[name] = (script.encode(), 0o644 if name.endswith('.cmd') else 0o755)
    app = 'PlexConfigControl Setup.app/Contents'
    for name, mode in (('Info.plist', 0o644), ('MacOS/setup', 0o755)):
        path = f'{app}/{name}'
        outer[path] = (read(f'deploy/{path}'), mode)
    for name in ('PlexConfigControl_macOS.command', 'PlexConfigControl_Instalator.py',
                 'PlexConfigControl_Installer.py'):
        outer[f'{app}/Resources/{name}'] = outer[name]
    write_zip(output / RELEASE_NAME, outer)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('commit')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    release(args.commit, args.output)
