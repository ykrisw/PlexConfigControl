"""Unprivileged test runtime with optional scoped reads; host writes disabled."""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from .connection_check import read_secret
from .installation import initialize_from_verifier
from .locking import operation_lock
from .startup import reconcile_startup
from .tls import ensure_tls
from .transport import build_client
from .web import Web
from .snapshots import Snapshots, SnapshotError
from .recovery import Recovery


@dataclass(frozen=True)
class Configuration:
    state: Path
    public_host: str
    port: int = 8443
    archives: Path | None = None
    truenas_url: str = ''
    api_username: str = ''
    api_key_file: str = ''
    ca_file: str | None = None
    snapshot_dataset: str | None = None

    def __post_init__(self):
        if self.snapshot_dataset is not None:
            if not all((self.truenas_url,self.api_username,self.api_key_file)):
                raise ValueError('Snapshot inspection requires a configured read-only TrueNAS connection')
            # Construction validates scope and performs no API/state access.
            Snapshots(None,None,self.snapshot_dataset)

    @classmethod
    def from_environment(cls,environment=None):
        env=os.environ if environment is None else environment
        if 'PCC_INITIAL_PASSWORD' in env:
            raise ValueError('Plaintext password environment variables are not supported')
        state=Path(env.get('PCC_STATE_DIRECTORY','/var/lib/plexconfigcontrol'))
        archives=env.get('PCC_ARCHIVE_DIRECTORY')
        port=int(env.get('PCC_PORT','8443'))
        host=env.get('PCC_PUBLIC_HOST','')
        if not state.is_absolute() or state.is_symlink() or not 1024<=port<=65535 or not host:
            raise ValueError('Invalid runtime configuration')
        if archives and (not Path(archives).is_absolute() or Path(archives).is_symlink() or not Path(archives).is_dir()):
            raise ValueError('Invalid archive read-only mount')
        url=env.get('PCC_TRUENAS_URL',''); user=env.get('PCC_API_USERNAME',''); key=env.get('PCC_API_KEY_FILE','')
        if any((url,user,key)) and not all((url,user,key)):
            raise ValueError('Incomplete read-only TrueNAS connection')
        return cls(state,host,port,Path(archives) if archives else None,url,user,key,env.get('PCC_CA_FILE'),env.get('PCC_PLEX_CONFIG_DATASET') or None)


class ReadOnlyTrueNAS:
    def __init__(self,client,snapshot_dataset=None):
        self.client=client
        self.snapshot_scope=Snapshots(None,None,snapshot_dataset) if snapshot_dataset is not None else None

    def call(self,method,*params):
        if method=='app.query':
            # Ignore caller filters: this runtime can inspect only Plex.
            return self.client.call('app.query',[['name','=','plex']],{'select':['name','state']})
        if method=='pool.snapshot.query' and self.snapshot_scope is not None and len(params)==1:
            filters=params[0]
            if (isinstance(filters,list) and len(filters)==1 and isinstance(filters[0],list)
                    and len(filters[0])==3 and filters[0][:2]==['id','=']):
                identifier=filters[0][2]
                try:
                    self.snapshot_scope._check(identifier)
                except SnapshotError:
                    raise PermissionError('Snapshot query is outside configured read-only scope') from None
                return self.client.call('pool.snapshot.query',[['id','=',identifier]])
        raise PermissionError('Only Plex status and explicitly scoped snapshot reads are enabled')


class TestApplication:
    """Explicit route boundary even if future Web routes add host operations."""
    READS={'/api/session','/api/settings','/api/translations','/api/status',
           '/api/operation','/api/recovery','/api/integration','/api/archives','/api/history','/api/restore/readiness',
           '/api/capabilities','/api/backup/plan','/api/account/photo','/api/account/photo/status'}
    POSTS={'/api/login','/api/logout','/api/account/password','/api/settings',
           '/api/history/detail','/api/history/download','/api/history/clear',
           '/api/restore/validate','/api/restore/cancel','/api/account/photo','/api/account/photo/remove'}
    def __init__(self,web): self.web=web
    def __call__(self,environ,start_response):
        method=environ.get('REQUEST_METHOD','GET'); path=environ.get('PATH_INFO','/')
        if path=='/healthz' and method=='GET':
            body=b'{"ready":true,"mode":"test"}'
            start_response('200 OK',[('Content-Type','application/json'),('Content-Length',str(len(body))),('Cache-Control','no-store')])
            return [body]
        allowed=(method=='GET' and (path=='/' or path.startswith('/assets/') or path in self.READS)) or (method=='POST' and path in self.POSTS)
        if not allowed:
            body=json.dumps({'error':'This operation is disabled in the test installation'}).encode()
            start_response('403 Forbidden',[('Content-Type','application/json'),('Content-Length',str(len(body))),('Cache-Control','no-store')])
            return [body]
        return self.web(environ,start_response)


def prepare(config,verifier=None):
    if config.state.is_symlink(): raise ValueError('State volume must not be a symlink')
    config.state.mkdir(mode=0o700,parents=True,exist_ok=True)
    api=None
    if config.truenas_url:
        api=ReadOnlyTrueNAS(build_client(config.truenas_url,config.api_username,
             read_secret(config.api_key_file),config.ca_file,timeout=10),config.snapshot_dataset)
    web=Web(config.state,archive_directory=config.archives,truenas_api=api,archive_deletion_enabled=False,archive_logs_enabled=False)
    if config.snapshot_dataset is not None:
        if api is None:
            raise ValueError('Snapshot inspection connection is unavailable')
        web.recovery_inspector=Recovery(api,web.operation_store,web.history,config.state,config.snapshot_dataset).inspect
    with operation_lock(config.state):
        with web.account.connect() as db:
            existing=db.execute('SELECT id FROM account WHERE id=1').fetchone()
        if not existing:
            if not verifier: raise ValueError('First installation requires PCC_BOOTSTRAP_VERIFIER')
            initialize_from_verifier(web.account,verifier)
        cert,key=ensure_tls(config.state,config.public_host)
    reconcile_startup(web.operation_store,web.progress,web.history,config.state)
    return TestApplication(web),cert,key


def main():
    try:
        if os.geteuid()==0: raise ValueError('The web application must run unprivileged')
        os.umask(0o077)
        config=Configuration.from_environment()
        verifier=os.environ.pop('PCC_BOOTSTRAP_VERIFIER',None)
        # Gunicorn loads this once per worker, including after a worker restart.
        # A single worker is required for the operation-thread ownership model.
        from gunicorn.app.base import BaseApplication
        class Server(BaseApplication):
            def load_config(self):
                from .tls import ensure_tls
                config.state.mkdir(parents=True,exist_ok=True,mode=0o700)
                with operation_lock(config.state):
                    cert,key=ensure_tls(config.state,config.public_host)
                for name,value in {'bind':f'0.0.0.0:{config.port}','workers':1,
                    'worker_class':'gthread','threads':4,'timeout':60,'graceful_timeout':60,
                    'certfile':str(cert),'keyfile':str(key),'worker_tmp_dir':'/tmp',
                    'accesslog':None,'errorlog':'-','capture_output':False,
                    'preload_app':False,'control_socket_disable':True,
                    'limit_request_line':4094,'limit_request_fields':50}.items():
                    self.cfg.set(name,value)
            def load(self): return prepare(config,verifier)[0]
        Server().run()
        return 0
    except Exception:
        # Never emit credentials, environment dumps or arbitrary API errors.
        print('PlexConfigControl could not start. Check non-root identity, volume access, installation verifier and TLS configuration.',flush=True)
        return 1


if __name__=='__main__': raise SystemExit(main())
