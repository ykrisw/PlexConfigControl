"""Administrator-only SSH maintenance of PCC's public API trust file.

Never changes the NAS certificate, credentials, Plex data, archive storage or
container definitions. Stops PCC before replacing its bind-mounted trust file.
"""
import hashlib
import fcntl
import json
import re
import subprocess
import os
from pathlib import Path
import stat
import socket
import tempfile
from urllib.parse import urlsplit
from .host_install import APP,InstallError,_ready
from .host_update import _details,_installed,_ensure_no_app_job,_stop,_sync_parent


def _read_ca(path):
    info=path.lstat()
    if (path.resolve(strict=True)!=path or not stat.S_ISREG(info.st_mode)
            or info.st_uid!=0 or info.st_mode&0o022 or info.st_size>262144):
        raise InstallError('Invalid private application CA file')
    return path.read_text()


def _replace(path,pem):
    from .installer_trust import public_certificates
    public_certificates(pem)
    fd,name=tempfile.mkstemp(prefix='.pcc-trust-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o644);stream.write(pem);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path);_sync_parent(path)
    finally:
        Path(name).unlink(missing_ok=True)


def _verify_worker_api(compose):
    command=compose['services']['worker']['command']
    def option(name):return command[command.index(name)+1]
    if (option('--api-username')!=APP or option('--api-key-file')!='/run/pcc-secrets/truenas-key'
            or option('--ca-file')!='/run/pcc-secrets/truenas-ca'):
        raise InstallError('Unexpected API credential configuration')
    result=subprocess.run(['docker','ps','-q','--no-trunc','--filter',f'label=com.docker.compose.project=ix-{APP}',
                           '--filter','label=com.docker.compose.service=worker'],capture_output=True,text=True,check=True,timeout=20)
    ids=result.stdout.splitlines()
    if len(ids)!=1 or not re.fullmatch(r'[a-f0-9]{12,64}',ids[0]):raise InstallError('Execution container identity could not be verified')
    probe=subprocess.run(['docker','exec','--user','568:568',ids[0],'python','-m','plexconfigcontrol.connection_check',
        '--url',option('--truenas-url'),'--username',APP,'--key-file','/run/pcc-secrets/truenas-key',
        '--ca-file','/run/pcc-secrets/truenas-ca'],capture_output=True,text=True,timeout=35)
    try:status=json.loads(probe.stdout)
    except (ValueError,TypeError):raise InstallError('API connection verification did not return a valid result') from None
    if probe.returncode or status.get('connected') is not True:
        from .connection_errors import CODES
        code=status.get('error_code')
        raise InstallError('TrueNAS API connection still requires attention'+(': '+code if code in CODES else ''))


def _repair_connection(api,client,verify_ca,supplied=None):
    if os.geteuid()!=0:raise PermissionError('Administrator required')
    _installed(api);compose=api.call('app.config',APP)
    update_record,endpoint=_details(compose)
    if update_record.exists():raise InstallError('Finish the recorded application update first')
    worker=compose['services']['worker'];command=worker['command']
    url=command[command.index('--truenas-url')+1]
    parsed=urlsplit(url)
    if parsed.scheme!='wss' or parsed.path!='/api/current' or not parsed.hostname:
        raise InstallError('Unexpected API endpoint')
    ca,=[Path(row['source']) for row in worker['volumes'] if row['target']=='/run/pcc-secrets/truenas-ca']
    if ca!=update_record.parent/'truenas-ca.pem':raise InstallError('Unexpected application trust location')
    old=_read_ca(ca)
    ui=client.call('system.general.config')
    if parsed.port!=ui['ui_httpsport']:raise InstallError('The TrueNAS API port changed; verify the endpoint before repair')
    addresses={row[4][0] for row in socket.getaddrinfo(parsed.hostname,parsed.port,type=socket.SOCK_STREAM)}
    if addresses!={endpoint.host_ip}:raise InstallError('The API hostname no longer resolves to this NAS; verify the endpoint before repair')
    pem=verify_ca(client,ui,endpoint.host_ip,parsed.hostname,ca,supplied)
    # A previous interrupted repair is resumed only for this exact compose/file pair.
    record=ca.with_name('connection-repair.json')
    identity=hashlib.sha256(json.dumps(compose,sort_keys=True).encode()).hexdigest()
    if record.exists():
        info=record.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o077 or info.st_size>1048576:
            raise InstallError('Invalid connection repair record')
        saved=json.loads(record.read_text())
        if saved['compose_sha256']!=identity or old not in (saved['previous_ca'],saved['candidate_ca']):
            raise InstallError('Application changed after the interrupted connection repair')
    print('Publiczny certyfikat TrueNAS potwierdzony przez uwierzytelnione SSH.',flush=True)
    if input('Wpisz tak, aby naprawić połączenie i uruchomić ponownie tylko PlexConfigControl: ').strip().lower()!='tak':
        raise InstallError('Connection repair cancelled')
    _stop(api,compose,trust_only=True)
    if not record.exists():
        fd=os.open(record,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump({'compose_sha256':identity,'previous_ca':old,'candidate_ca':pem},stream)
            stream.flush();os.fsync(stream.fileno())
        _sync_parent(record)
    # Recheck both inputs immediately before updating the stopped application's public file.
    if _installed(api)!='STOPPED' or api.call('app.config',APP)!=compose or _read_ca(ca)!=old:raise InstallError('Application changed before repair')
    _replace(ca,pem)
    try:
        api.start();_ready(endpoint);_verify_worker_api(compose)
    except Exception:
        raise InstallError('Connection trust was updated. The repair record is retained; rerun Repair connection to verify startup.') from None
    record.unlink();_sync_parent(record)
    print(f'Połączenie naprawione. Otwórz https://{endpoint.host_ip}:{endpoint.host_port}',flush=True)


def repair_connection(api,client,verify_ca,supplied=None):
    if os.geteuid()!=0:raise PermissionError('Administrator required')
    fd=os.open('/run/plexconfigcontrol-update.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise InstallError('Another application maintenance operation is active') from None
        return _repair_connection(api,client,verify_ca,supplied)
