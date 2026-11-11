"""Build the explicit-opt-in, standard-library-only snapshot diagnostic."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT/'deploy/qnap/PCC_QNAP_Snapshot_Probe.py'


def build():
    snapshot = (ROOT/'plexconfigcontrol/qnap_snapshot_probe.py').read_text()
    relative_import = 'from .qnap_api import QnapApiError\n'
    assert snapshot.count(relative_import) == 1
    snapshot = snapshot.replace(relative_import, '')
    content = '\n\n'.join([
        '#!/usr/bin/env python3\n# PlexConfigControl — developer snapshot diagnostic. MIT license.\n',
        (ROOT/'plexconfigcontrol/qnap_discovery.py').read_text(),
        (ROOT/'plexconfigcontrol/qnap_api.py').read_text(),
        snapshot,
        (ROOT/'deploy/qnap/snapshot_probe_main.py').read_text(),
    ])
    compile(content, str(OUTPUT), 'exec')
    OUTPUT.write_text(content)
    return OUTPUT


if __name__ == '__main__':
    import hashlib
    output = build()
    print(output.name, hashlib.sha256(output.read_bytes()).hexdigest())
