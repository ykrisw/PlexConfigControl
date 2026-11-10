"""Combine tested native installers into one portable download."""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import tarfile
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

NAME = 'PlexConfigControl_Installer_Windows_macOS_Linux_PL_EN.zip'
ROOT = Path(__file__).resolve().parents[2]


def package(artifacts, output):
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as temporary:
        work = Path(temporary)
        bundle = work / 'bundle'
        bundle.mkdir()
        targets = {
            'windows': bundle / 'Windows',
            'linux': bundle / 'Linux',
            'macos-x86_64': bundle / 'PlexConfigControl Setup.app/Contents/Resources/x86_64',
            'macos-arm64': bundle / 'PlexConfigControl Setup.app/Contents/Resources/arm64',
        }
        for platform, destination in targets.items():
            destination.mkdir(parents=True)
            with tarfile.open(artifacts / f'{platform}.tar.gz') as archive:
                archive.extractall(destination, filter='data')
        app = bundle / 'PlexConfigControl Setup.app/Contents'
        (app / 'MacOS').mkdir()
        (app / 'Info.plist').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.plexconfigcontrol.desktop-setup</string>
<key>CFBundleName</key><string>PlexConfigControl Setup</string>
<key>CFBundleExecutable</key><string>launch</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>4</string>
</dict></plist>
''')
        launcher = app / 'MacOS/launch'
        launcher.write_text('''#!/bin/sh
set -eu
arch=$(uname -m)
case "$arch" in arm64|x86_64) ;; *) exit 1 ;; esac
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec "$root/Resources/$arch/PlexConfigControl Setup.app/Contents/MacOS/PlexConfigControl Setup" "$@"
''')
        launcher.chmod(0o755)
        for name in ('INSTALL-EN.md', 'INSTRUKCJA-PL.md', 'LICENSE'):
            (bundle / name).write_bytes((ROOT / name).read_bytes())
        (bundle / 'BUILD-INFO.txt').write_text('PlexConfigControl 1.0.10\nNative installers for Windows x64, Linux x64 and macOS Intel/Apple Silicon.\n')
        result = output / NAME
        with ZipFile(result, 'w', compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(bundle.rglob('*')):
                if path.is_dir() and not path.is_symlink():
                    continue
                entry = ZipInfo(path.relative_to(bundle).as_posix())
                entry.create_system = 3
                entry.external_attr = path.lstat().st_mode << 16
                entry.compress_type = ZIP_DEFLATED
                content = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
                archive.writestr(entry, content)
        checksum = hashlib.sha256(result.read_bytes()).hexdigest()
        (output / 'SHA256SUMS').write_text(f'{checksum}  {NAME}\n')
        print(result, checksum)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    package(args.artifacts, args.output)
