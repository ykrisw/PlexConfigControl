"""Remove only unused, explicitly named PCC image tags; never global prune."""
import json
import re
import subprocess

REPOSITORIES = {'plexconfigcontrol', 'plexconfigcontrol-worker'}

def _run(*args):
    return subprocess.run(['docker', *args], check=True, capture_output=True,
                          text=True, timeout=30).stdout.splitlines()

def prune_unused(keep):
    """Keep the current or rollback pair and any images used by containers."""
    try:
        if not keep or any(not re.fullmatch(r'(plexconfigcontrol|plexconfigcontrol-worker):[A-Za-z0-9_.-]+', ref) for ref in keep):
            raise ValueError('Invalid retained PCC image references')
        retained = set(_run('image', 'inspect', '--format', '{{.Id}}', *sorted(keep)))
        if len(retained) < 1 or any(not re.fullmatch(r'sha256:[a-f0-9]{64}', value) for value in retained):
            raise ValueError('Unconfirmed retained images')
        containers = _run('ps', '-aq', '--no-trunc')
        if any(not re.fullmatch(r'[a-f0-9]{64}', value) for value in containers):
            raise ValueError('Unconfirmed container inventory')
        used = set(_run('inspect', '--type', 'container', '--format', '{{.Image}}', *containers)) if containers else set()
        if any(not re.fullmatch(r'sha256:[a-f0-9]{64}', value) for value in used):
            raise ValueError('Unconfirmed container images')
        rows = [json.loads(line) for line in _run('image', 'ls', '--no-trunc', '--format', '{{json .}}')]
        for row in rows:
            repo, tag, identity = row['Repository'], row['Tag'], row['ID']
            if repo not in REPOSITORIES or not re.fullmatch(r'[A-Za-z0-9_.-]+', tag):continue
            ref = repo + ':' + tag
            if ref in keep or identity in retained or identity in used:continue
            if not re.fullmatch(r'sha256:[a-f0-9]{64}', identity):raise ValueError('Invalid image identity')
            try:_run('image', 'rm', ref)
            except (OSError, subprocess.SubprocessError):
                print('PCC: an unused image could not be removed; no removal was forced.', flush=True)
        return True
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        print('PCC: image cleanup skipped because safe ownership/use could not be confirmed.', flush=True)
        return False

def compose_images(compose):
    try:return {compose['services'][name]['image'] for name in ('panel','worker')}
    except (KeyError,TypeError):return set()
