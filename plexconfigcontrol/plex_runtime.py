"""Identify the running TrueNAS Plex container and its bundled SQLite."""
import re
import subprocess
import sys


class PlexRuntimeError(RuntimeError):
    pass


def detect_plex_runtime(*, runner=subprocess.run):
    def docker(*args):
        try:
            result = runner(['docker', *args], check=True, capture_output=True, text=True, timeout=20)
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise PlexRuntimeError('Nie można odczytać obrazu lub wersji SQLite uruchomionego Plexa.') from None

    container = docker('ps', '--no-trunc', '--filter', 'label=com.docker.compose.project=ix-plex',
                       '--filter', 'label=com.docker.compose.service=plex', '--format', '{{.ID}}')
    if not re.fullmatch(r'[0-9a-f]{64}', container):
        raise PlexRuntimeError('Uruchom jedną aplikację Plex o nazwie plex w TrueNAS Apps.')
    image = docker('inspect', '--type', 'container', '--format', '{{.Image}}', container)
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise PlexRuntimeError('Nie można potwierdzić identyfikatora obrazu Plexa.')

    digests = docker('image', 'inspect', '--format', '{{range .RepoDigests}}{{println .}}{{end}}', image)
    references = sorted({ref for ref in digests.splitlines() if re.fullmatch(
        r'(?:(?:docker\.io|index\.docker\.io)/)?plexinc/pms-docker@sha256:[0-9a-f]{64}', ref)})
    if not references:
        raise PlexRuntimeError('Potrzebny jest oficjalny obraz Plexa z identyfikatorem SHA-256.')
    reference = references[0]
    verified = docker('image', 'inspect', '--format', '{{.Id}} {{.Os}}/{{.Architecture}}', reference)
    if verified != f'{image} linux/amd64':
        raise PlexRuntimeError('Obraz Plexa musi odpowiadać uruchomionemu kontenerowi Linux x86-64.')

    output = docker('exec', container, '/usr/lib/plexmediaserver/Plex SQLite', '-version')
    match = re.fullmatch(r'([0-9]+\.[0-9]+\.[0-9]+)(?:[ \t]+[^\r\n]+)?', output)
    if match is None:
        raise PlexRuntimeError('Nie można potwierdzić wersji SQLite dostarczonej z Plexem.')
    return reference, match[1], container, image


if __name__ == '__main__':
    try:
        print(' '.join(detect_plex_runtime()))
    except PlexRuntimeError as error:
        sys.exit(str(error))
