"""Build the single-file, standard-library-only QNAP read compatibility probe."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT/'deploy/qnap/PCC_QNAP_API_Probe.py'


def build():
    parts = [
        '#!/usr/bin/env python3\n# PlexConfigControl — developer read-only API probe. MIT license.\n',
        (ROOT/'plexconfigcontrol/qnap_discovery.py').read_text(),
        (ROOT/'plexconfigcontrol/qnap_api.py').read_text(),
        (ROOT/'deploy/qnap/probe_main.py').read_text(),
    ]
    content = '\n\n'.join(parts)
    compile(content, str(OUTPUT), 'exec')
    OUTPUT.write_text(content)
    return OUTPUT


if __name__ == '__main__':
    import hashlib
    output = build()
    print(output.name, hashlib.sha256(output.read_bytes()).hexdigest())
