"""Build a native desktop executable including both server installer payloads."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]


def build(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as temporary:
        work = Path(temporary)
        subprocess.run([sys.executable, 'deploy/build_release.py', 'HEAD', str(work / 'release')],
                       cwd=ROOT, check=True)
        payload = work / 'payload'
        payload.mkdir()
        with ZipFile(next((work / 'release').glob('*.zip'))) as archive:
            for filename in ('PlexConfigControl_Instalator.py', 'PlexConfigControl_Installer.py'):
                (payload / filename).write_bytes(archive.read(filename))
        command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                   '--windowed', '--name', 'PlexConfigControl Setup',
                   '--add-data', str(payload) + ':payload',
                   '--distpath', str(output), '--workpath', str(work / 'build'),
                   '--specpath', str(work), str(ROOT / 'deploy/desktop/setup_app.py')]
        if sys.platform != 'darwin':
            command.insert(5, '--onefile')
        subprocess.run(command, cwd=ROOT, check=True)
        if sys.platform == 'darwin':
            shutil.rmtree(output / 'PlexConfigControl Setup', ignore_errors=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    build(parser.parse_args().output)
