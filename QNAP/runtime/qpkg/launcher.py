#!/usr/bin/env python3
"""QNAP lifecycle: unprivileged panel and fixed-purpose snapshot backup worker."""
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'lib'),str(ROOT/'app')]
os.environ['PYTHONTZPATH']=str(ROOT/'lib/tzdata/zoneinfo')

import argparse
import errno
import grp
import hashlib
import hmac
import json
import pwd
import secrets
import signal
import socket
import socketserver
import stat
import struct
import ssl
import http.client
import subprocess
import threading
import time
import re

VAR=ROOT/'var'
OWNER=VAR/'owner'
PANEL=VAR/'panel'
IPC=VAR/'ipc'
CONFIG=OWNER/'service.json'
SOCKET=IPC/'status.sock'
PID=OWNER/'supervisor.json'
NAME='PCC'
DEFAULT_PORT=8443


def write_json(path,value,mode=0o600):
    fd=os.open(path.with_suffix('.tmp'),os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
    os.replace(path.with_suffix('.tmp'),path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def qpkg_setting(field,value):
    if field not in ('WebUI','Web_Port','Web_SSL_Port'):
        raise ValueError('Unsupported package setting')
    current=subprocess.run(['/sbin/getcfg',NAME,field,'-f','/etc/config/qpkg.conf'],capture_output=True,text=True,timeout=10,check=True)
    if current.stdout.strip()==str(value):return
    subprocess.run(['/sbin/setcfg',NAME,field,str(value),'-f','/etc/config/qpkg.conf'],check=True,
                   stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=10)


def configure_ipc(uid):
    info=IPC.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0:
        raise ValueError('Unexpected IPC directory identity')
    os.chown(IPC,0,uid)
    # mkdir's requested 0710 is masked to 0700 by the service umask 0077.
    # Restore group traversal explicitly; only this package's panel GID gains it.
    os.chmod(IPC,0o710)


def read_private_record(path,limit=16384):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'r') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077 or info.st_size>limit:
            raise ValueError('Invalid private application record')
        return json.load(stream)


def validate_service_config(config):
    if (config.get('version')!=1 or type(config.get('uid'))is not int or not 60000<=config['uid']<61000
            or type(config.get('port'))is not int or not 1024<=config['port']<=65535):
        raise ValueError('Invalid service configuration')
    if config['uid'] in {r.pw_uid for r in pwd.getpwall()} or config['uid'] in {r.gr_gid for r in grp.getgrall()}:
        raise ValueError('Reserved service identity conflicts with a NAS account')


def register_web(config):
    token_path=PANEL/'setup-token'
    suffix='/'
    if token_path.exists() or token_path.is_symlink():
        fd=os.open(token_path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'r') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>128:raise ValueError('Invalid setup token file')
            token=stream.read(129).strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,64}',token):raise ValueError('Invalid setup token')
        suffix='/#setup='+token
    qpkg_setting('WebUI',suffix)
    qpkg_setting('Web_Port',config['port'])
    qpkg_setting('Web_SSL_Port',config['port'])


def initialize():
    if os.geteuid()!=0:raise PermissionError('Root required for package initialization')
    if CONFIG.exists():
        config=read_private_record(CONFIG);validate_service_config(config)
        configure_ipc(config['uid'])
        register_web(config)
        return config
    VAR.mkdir(mode=0o711,exist_ok=True);os.chmod(VAR,0o711)
    OWNER.mkdir(mode=0o700);PANEL.mkdir(mode=0o700);IPC.mkdir(mode=0o710)
    used={r.pw_uid for r in pwd.getpwall()}|{r.gr_gid for r in grp.getgrall()}
    uid=next(v for v in range(60000,61000) if v not in used)
    os.chown(PANEL,uid,uid);configure_ipc(uid)
    config={'version':1,'uid':uid,'port':DEFAULT_PORT}
    token=secrets.token_urlsafe(32)
    secret=PANEL/'setup-token'
    fd=os.open(secret,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(token)
    os.chown(secret,uid,uid)
    write_json(CONFIG,config)
    register_web(config)
    return config


def process_identity(pid):
    text=Path('/proc/'+str(pid)+'/stat').read_text()
    start=text[text.rfind(')')+2:].split()[19]
    return {'pid':pid,'start':start,'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def self_test():
    import gzip,sqlite3,ssl,ctypes,fcntl
    import gunicorn,PIL,cryptography,websocket,tzdata
    from cryptography.hazmat.primitives.asymmetric import ec
    from PIL import Image
    from zoneinfo import ZoneInfo
    from plexconfigcontrol.web import Web
    from plexconfigcontrol.qnap_discovery import discover_qnap_plex
    assert gzip.decompress(gzip.compress(b'pcc'))==b'pcc'
    with sqlite3.connect(':memory:') as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert ZoneInfo('Europe/London').key=='Europe/London'
    ec.generate_private_key(ec.SECP256R1())
    assert Image.new('RGB',(2,2)).resize((4,4)).size==(4,4)
    from plexconfigcontrol.qnap_service import QnapBackupService
    from plexconfigcontrol.qnap_web import QnapWeb
    result=subprocess.run([str(ROOT/'tar/bin/pcc-tar'),'--version'],check=True,capture_output=True,text=True,timeout=5)
    assert 'GNU tar' in result.stdout
    print('Private Python, TLS, SQLite, image libraries and panel imports: OK',flush=True)


class StatusHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(10)
        uid=struct.unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
        if uid!=self.server.panel_uid:return
        line=self.rfile.readline(65537)
        if len(line)>65536 or not line.endswith(b'\n'):return
        if line==b'{"action":"plex"}\n':
            from plexconfigcontrol.qnap_discovery import discover_qnap_plex
            from plexconfigcontrol.qnap_runtime import plex_process_state
            try:state=plex_process_state(discover_qnap_plex())
            except Exception:state='UNKNOWN'
            result=[{'name':'plex','state':state}]
        else:
            from plexconfigcontrol.qnap_service import QnapServiceError
            from plexconfigcontrol.qnap_restore import QnapRestoreError
            from plexconfigcontrol.qnap_api import QnapApiError
            try:
                data=json.loads(line)
                if not isinstance(data,dict) or set(data)!={'action','data'} or not isinstance(data['action'],str) or not isinstance(data['data'],dict):raise ValueError()
                result={'ok':True,'result':self.server.service.dispatch(data['action'],data['data'])}
            except (QnapServiceError,QnapApiError,QnapRestoreError) as error:result={'ok':False,'error':str(error)}
            except (ValueError,TypeError,KeyError):result={'ok':False,'error':'Invalid QNAP service request'}
            except Exception:result={'ok':False,'error':'QNAP operation could not be confirmed; review its status'}
        try:self.wfile.write(json.dumps(result).encode()+b'\n')
        except (BrokenPipeError,ConnectionResetError):pass


class StatusClient:
    def exchange(self,payload,limit=8*1024*1024):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(50);connection.connect(str(SOCKET))
            if struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]!=0:
                raise PermissionError('Unexpected service owner')
            connection.sendall(payload)
            with connection.makefile('rb') as stream:line=stream.readline(limit+1)
        if len(line)>limit or not line.endswith(b'\n'):raise ValueError('Incomplete service response')
        return json.loads(line)
    def call(self,method,*params):
        if method!='app.query':raise PermissionError('Read-only Plex status only')
        return self.exchange(b'{"action":"plex"}\n',1024)
    def request(self,action,data):
        from plexconfigcontrol.qnap_web import QnapRemoteError
        result=self.exchange(json.dumps({'action':action,'data':data}).encode()+b'\n')
        if result.get('ok') is not True:raise QnapRemoteError(result.get('error','QNAP operation is unavailable'))
        return result['result']


class PreviewApplication:
    def __init__(self):
        from plexconfigcontrol.auth import Account
        self.account=Account(PANEL)
        self.web=None
    def initialized(self):
        with self.account.connect() as db:return db.execute('SELECT id FROM account WHERE id=1').fetchone() is not None
    def __call__(self,environ,start_response):
        path=environ.get('PATH_INFO','/')
        if path=='/healthz' and environ['REQUEST_METHOD']=='GET':
            return self.reply(start_response,'200 OK',{'ready':True,'mode':'qnap-install-preview','configured':self.initialized()})
        if not self.initialized():
            if path=='/' and environ['REQUEST_METHOD']=='GET':
                data=(ROOT/'setup.html').read_bytes()
                start_response('200 OK',[('Content-Type','text/html; charset=utf-8'),('Content-Length',str(len(data))),('Cache-Control','no-store'),('Referrer-Policy','no-referrer')])
                return [data]
            if path=='/setup' and environ['REQUEST_METHOD']=='POST':
                return self.setup(environ,start_response)
            return self.reply(start_response,'403 Forbidden',{'error':'Complete first-run setup in App Center.'})
        if self.web is None:
            from plexconfigcontrol.web import Web
            from plexconfigcontrol.qnap_web import QnapWeb
            self.web=QnapWeb(Web(PANEL,truenas_api=StatusClient(),archive_deletion_enabled=False,archive_logs_enabled=False),StatusClient())
        if path in ('/assets/qnap-tools.mjs','/assets/qnap-tools.css') and environ['REQUEST_METHOD']=='GET':
            body=(ROOT/'app/plexconfigcontrol/static'/Path(path).name).read_bytes()
            kind='text/javascript' if path.endswith('.mjs') else 'text/css'
            start_response('200 OK',[('Content-Type',kind),('Content-Length',str(len(body))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]);return [body]
        if path=='/' and environ['REQUEST_METHOD']=='GET':
            body=(ROOT/'app/plexconfigcontrol/static/index.html').read_text()
            body=body.replace('</head>','<link rel="stylesheet" href="/assets/qnap-tools.css"><script type="module" src="/assets/qnap-tools.mjs"></script></head>').encode()
            start_response('200 OK',[('Content-Type','text/html; charset=utf-8'),('Content-Length',str(len(body))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('X-Frame-Options','DENY'),
                ('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]);return [body]
        return self.web(environ,start_response)
    @staticmethod
    def reply(start_response,code,data):
        body=json.dumps(data).encode();start_response(code,[('Content-Type','application/json'),('Content-Length',str(len(body))),('Cache-Control','no-store')]);return [body]
    def setup(self,environ,start_response):
        try:
            if environ.get('wsgi.url_scheme')!='https' or environ.get('HTTP_ORIGIN')!='https://'+environ.get('HTTP_HOST',''):
                raise ValueError('Use the same HTTPS origin')
            length=int(environ.get('CONTENT_LENGTH','0'))
            if not 0<length<=16384:raise ValueError('Invalid request size')
            data=json.loads(environ['wsgi.input'].read(length))
            if set(data)!={'token','password','confirmation','language','port'}:raise ValueError('Invalid fields')
            token=(PANEL/'setup-token').read_text()
            if not isinstance(data['token'],str) or not hmac.compare_digest(token,data['token']):raise ValueError('Open setup from QNAP App Center')
            if not isinstance(data['password'],str) or not 1<=len(data['password'])<=4096 or data['password']!=data['confirmation']:raise ValueError('Passwords must match')
            if type(data['port']) is not int or not 1024<=data['port']<=65535:raise ValueError('Use a port from 1024 to 65535')
            if data['language'] not in ('pl','en'):raise ValueError('Choose Polish or English')
            from plexconfigcontrol.settings import Settings
            settings=Settings(PANEL)
            settings.update(language=data['language'])
            self.account.initialize(data['password'])
            write_json(PANEL/'setup-complete.json',{'port':data['port']})
            (PANEL/'setup-token').unlink()
            return self.reply(start_response,'200 OK',{'ok':True,'port':data['port']})
        except (ValueError,KeyError,TypeError,FileNotFoundError):
            return self.reply(start_response,'400 Bad Request',{'error':'Setup could not be completed. Check the App Center link and form values.'})


def web_child():
    config=json.loads(CONFIG.read_text())
    os.setgroups([]);os.setgid(config['uid']);os.setuid(config['uid']);os.umask(0o077)
    from plexconfigcontrol.tls import ensure_tls
    cert,key=ensure_tls(PANEL,'localhost')
    from gunicorn.app.base import BaseApplication
    class Server(BaseApplication):
        def load_config(self):
            for name,value in {'bind':'0.0.0.0:'+str(config['port']),'workers':1,'worker_class':'gthread',
                'threads':4,'timeout':60,'graceful_timeout':20,'certfile':str(cert),'keyfile':str(key),
                'accesslog':None,'errorlog':'-','worker_tmp_dir':str(PANEL),
                'control_socket_disable':True,'limit_request_line':4094,'limit_request_fields':50}.items():self.cfg.set(name,value)
        def load(self):return PreviewApplication()
    Server().run()


def supervise():
    config=initialize();self_test()
    lock=os.open(OWNER/'service.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    os.lockf(lock,os.F_TLOCK,0)
    record=process_identity(os.getpid());write_json(PID,record)
    (VAR/'service.pid').write_text(str(os.getpid()))
    os.chmod(VAR/'service.pid',0o600)
    if SOCKET.exists() or SOCKET.is_symlink():SOCKET.unlink()
    server=socketserver.ThreadingUnixStreamServer(str(SOCKET),StatusHandler)
    from plexconfigcontrol.qnap_service import QnapBackupService
    server.service=QnapBackupService(OWNER,ROOT/'tar/bin/pcc-tar')
    server.daemon_threads=True;server.panel_uid=config['uid']
    os.chown(SOCKET,0,config['uid']);os.chmod(SOCKET,0o660)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    stopping=threading.Event()
    def request_stop(*args):
        # Refuse a routine stop while a root worker is using its owned snapshot.
        if not server.service.busy:stopping.set()
    signal.signal(signal.SIGTERM,request_stop)
    signal.signal(signal.SIGINT,request_stop)
    child=None
    def start():
        return subprocess.Popen([str(ROOT/'python/bin/python3'),'-I','-S',str(ROOT/'launcher.py'),'--web-child'],start_new_session=True,cwd=ROOT)
    def stop_child():
        if child is None or child.poll() is not None:return
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:child.wait(timeout=25)
        except subprocess.TimeoutExpired:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait()
    try:
        child=start()
        while not stopping.wait(1):
            if child.poll() is not None:raise RuntimeError('Unprivileged panel stopped')
            complete=PANEL/'setup-complete.json'
            if complete.exists():
                info=complete.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_size>128:raise ValueError('Invalid setup completion')
                selected=json.loads(complete.read_text())
                if set(selected)!={'port'} or type(selected['port']) is not int or not 1024<=selected['port']<=65535:raise ValueError('Invalid selected port')
                qpkg_setting('WebUI','/');qpkg_setting('Web_Port',selected['port']);qpkg_setting('Web_SSL_Port',selected['port'])
                if selected['port']!=config['port']:
                    stop_child();config['port']=selected['port'];write_json(CONFIG,config);child=start()
                complete.unlink()
    finally:
        stop_child();server.shutdown();server.server_close()
        SOCKET.unlink(missing_ok=True);PID.unlink(missing_ok=True)
        (VAR/'service.pid').unlink(missing_ok=True)
        os.close(lock)


def status():
    record=json.loads(PID.read_text())
    if process_identity(record['pid'])!=record:raise ValueError('Supervisor identity changed')
    config=json.loads(CONFIG.read_text())
    context=ssl.create_default_context(cafile=str(PANEL/'tls/panel.crt'))
    connection=http.client.HTTPSConnection('127.0.0.1',config['port'],context=context,timeout=3)
    try:
        connection.request('GET','/healthz')
        response=connection.getresponse()
        payload=json.loads(response.read(4096))
        if response.status!=200 or payload.get('mode')!='qnap-install-preview' or payload.get('ready') is not True:
            raise ValueError('Panel is not ready')
    finally:connection.close()


def can_maintain():
    pointer=OWNER/'qnap-current.json'
    if pointer.exists():
        identifier=read_private_record(pointer)['request_id']
        if not isinstance(identifier,str) or not re.fullmatch(r'[0-9a-f]{32}',identifier):raise ValueError('Invalid operation record')
        job=read_private_record(OWNER/'qnap-jobs'/(identifier+'.json'),262144)
        if job['state'] in ('QUEUED','RUNNING','RECOVERY_REQUIRED','VALIDATING','WAITING_FOR_PLEX_STOP') or job.get('restore',{}).get('workspace_identity'):
            raise RuntimeError('Finish the active backup or its recorded recovery before stopping, updating or removing PCC')


def stop():
    can_maintain()
    if not PID.exists():return
    record=json.loads(PID.read_text())
    try:
        if process_identity(record['pid'])!=record:raise ValueError('Supervisor process identity changed')
        executable=Path(os.readlink('/proc/'+str(record['pid'])+'/exe')).resolve()
        if executable!=(ROOT/'python/bin/python3').resolve():raise ValueError('Unexpected supervisor executable')
        arguments=Path('/proc/'+str(record['pid'])+'/cmdline').read_bytes().split(b'\0')
        if str(ROOT/'launcher.py').encode() not in arguments or b'--supervise' not in arguments:raise ValueError('Unexpected supervisor command')
        os.kill(record['pid'],signal.SIGTERM)
        for attempt in range(35):
            if not Path('/proc/'+str(record['pid'])).exists() or not PID.exists():return
            time.sleep(1)
        raise RuntimeError('Supervisor did not stop; no unverified kill was sent')
    except FileNotFoundError:PID.unlink(missing_ok=True)


def main():
    os.umask(0o077)
    action=sys.argv[1:]
    if action==['--self-test']:self_test()
    elif action==['--initialize']:initialize()
    elif action==['--supervise']:supervise()
    elif action==['--web-child']:web_child()
    elif action==['--stop']:stop()
    elif action==['--can-maintain']:can_maintain()
    elif action==['--status']:status()
    else:raise ValueError('Select one package lifecycle action')

if __name__=='__main__':main()
