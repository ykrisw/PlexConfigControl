"""Turn a release ZIP into a single-file TrueNAS installer."""
import argparse
import base64
import hashlib
import textwrap
from pathlib import Path
from zipfile import ZipFile


ENTRY_POINT = "PlexConfigControl_RC_Install/INSTALUJ.sh"

LAUNCHER = """#!/usr/bin/env python3
# PlexConfigControl installer for TrueNAS x86-64.
import base64
import hashlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile


def main():
    if sys.argv[1:] in (["--help"], ["-h"]):
        print("Uruchom w Shell TrueNAS: sudo python3 " + Path(__file__).name)
        print("Możesz też dopisać opcje kreatora, np. sprawdz.")
        return 0
    if os.geteuid() != 0:
        print("Uruchom instalator przez sudo w Shell TrueNAS.", file=sys.stderr)
        return 1
    package = base64.b64decode(PACKAGE)
    if hashlib.sha256(package).hexdigest() != SHA256:
        print("Paczka wewnątrz instalatora jest uszkodzona. Pobierz plik ponownie.", file=sys.stderr)
        return 1
    env = dict(os.environ, PCC_INSTALLER_FILE=str(Path(__file__).resolve()))
    with tempfile.TemporaryDirectory(prefix="pcc-rc.", dir="/var/tmp") as directory:
        work = Path(directory)
        with ZipFile(io.BytesIO(package)) as archive:
            archive.extractall(work)
        start = work / ENTRY_POINT
        print("Paczka sprawdzona. Uruchamiam kreator PlexConfigControl.", flush=True)
        return subprocess.call(["sh", str(start), *sys.argv[1:]], env=env)


"""


def build(source, output, *, entry_point=ENTRY_POINT, launcher=LAUNCHER):
    package = source.read_bytes()
    with ZipFile(source) as archive:
        if entry_point not in archive.namelist() or archive.testzip() is not None:
            raise ValueError("Expected a complete PlexConfigControl release ZIP")
    payload = "\n".join(textwrap.wrap(base64.b64encode(package).decode("ascii"), width=76))
    with output.open("x", encoding="utf-8") as file:
        file.write(launcher)
        file.write(f"ENTRY_POINT = {entry_point!r}\n")
        file.write(f"SHA256 = {hashlib.sha256(package).hexdigest()!r}\n")
        file.write(f'PACKAGE = """\n{payload}\n"""\n')
        file.write('\nif __name__ == "__main__":\n    sys.exit(main())\n')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_zip", type=Path)
    parser.add_argument("installer", type=Path)
    args = parser.parse_args()
    build(args.release_zip, args.installer)
