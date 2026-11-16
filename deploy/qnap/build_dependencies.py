#!/usr/bin/env python3
"""Build-host helper: stage offline dependencies for the QNAP development QPKG.

Never invoke pip on the NAS or install into its system Python. The resulting
lib directory will be carried inside PlexConfigControl's own package directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


LOCK = Path(__file__).with_name('requirements-cp312-x86_64.txt')
TARGET = ['--only-binary=:all:', '--platform', 'manylinux_2_28_x86_64',
          '--platform', 'manylinux_2_17_x86_64', '--platform', 'manylinux2014_x86_64',
          '--python-version', '3.12', '--implementation', 'cp',
          '--abi', 'cp312', '--abi', 'abi3', '--abi', 'none']


SMOKE = '''
import sys
sys.path.insert(0, sys.argv[1])
import gunicorn, cryptography, PIL, websocket, tzdata
from cryptography.hazmat.primitives.asymmetric import ec
from PIL import Image
from zoneinfo import ZoneInfo, reset_tzpath
ec.generate_private_key(ec.SECP256R1())
assert Image.new('RGB', (8, 8)).resize((4, 4)).size == (4, 4)
reset_tzpath([])
assert ZoneInfo('Europe/London').key == 'Europe/London'
for module in (gunicorn, cryptography, PIL, websocket, tzdata):
    from pathlib import Path
    assert Path(sys.argv[1]).resolve() in Path(module.__file__).resolve().parents
print('QNAP dependency smoke test passed (host Python 3.12/x86_64 only).')
'''


def pip(*args):
    subprocess.run([sys.executable, '-m', 'pip', '--isolated',
                    '--disable-pip-version-check', *args], check=True)


def build(output, wheelhouse=None):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Output must not already exist')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pcc-qnap-deps-', dir=output.parent) as temp:
        stage = Path(temp)
        wheels = Path(wheelhouse).resolve(strict=True) if wheelhouse else stage/'wheels'
        if wheelhouse is None:
            wheels.mkdir()
            pip('download', *TARGET, '--require-hashes', '--dest', str(wheels),
                '--requirement', str(LOCK))
        library = stage/'lib'
        # No source build scripts and no network during installation. pip checks
        # the committed hashes and the complete locked dependency graph.
        pip('install', *TARGET, '--no-index', '--find-links', str(wheels),
            '--require-hashes', '--no-compile', '--no-warn-script-location',
            '--target', str(library), '--requirement', str(LOCK))
        # Console wrappers embed this temporary build path and are not used by
        # the QPKG. Start gunicorn through the package's Python launcher instead.
        import shutil
        shutil.rmtree(library/'bin', ignore_errors=True)
        manifest = {}
        for path in sorted(library.rglob('*')):
            if path.is_file():
                manifest[path.relative_to(library).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        (library/'pcc-dependency-manifest.json').write_text(json.dumps({
            'target': 'cp312-x86_64-manylinux_2_28',
            'lock_sha256': hashlib.sha256(LOCK.read_bytes()).hexdigest(),
            'files': manifest,
        }, sort_keys=True, indent=2)+'\n')
        os.rename(library, output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--wheelhouse', type=Path,
                        help='Use an existing wheel directory without network access')
    parser.add_argument('--smoke-test', action='store_true',
                        help='Requires a Linux x86_64 CPython 3.12 build host')
    args = parser.parse_args()
    if args.smoke_test:
        import platform
        if (sys.version_info[:2] != (3, 12) or sys.platform != 'linux'
                or platform.machine() != 'x86_64'):
            parser.error('Smoke test requires Linux x86_64 CPython 3.12')
    library = build(args.output, args.wheelhouse)
    if args.smoke_test:
        subprocess.run([sys.executable, '-I', '-S', '-c', SMOKE, str(library)], check=True)
    print('Staged QNAP dependencies:', library)


if __name__ == '__main__':
    main()
