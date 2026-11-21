"""Disposable GitHub CI: actual containers must start with an untrusted API.

No NAS or real Plex directories are mounted. All certificates/keys are fixtures.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from uuid import uuid4
from plexconfigcontrol.installation import password_verifier


def run(*args,check=True):
    return subprocess.run(args,text=True,capture_output=True,check=check,timeout=120)


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true' or Path('/usr/bin/midclt').exists() or Path('/sbin/getcfg').exists():
        raise SystemExit('Disposable GitHub runner only; never run this on a NAS')
    identity='pcc-tls-'+uuid4().hex[:10];network=identity+'-net';containers=[]
    with tempfile.TemporaryDirectory(prefix='pcc-tls-offline-') as folder:
        root=Path(folder)
        for name in ('state','archives','config','tls'): (root/name).mkdir()
        (root/'archives/Logs').mkdir();(root/'archives/keep').write_text('archive fixture')
        (root/'config/keep').write_text('Plex fixture')
        (root/'key').write_text('dummy-ci-api-key');(root/'key').chmod(0o600)
        for prefix,cn in (('trusted','trusted-fixture'),('untrusted','api-fixture')):
            run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN='+cn,
                '-addext','subjectAltName=DNS:'+cn,'-keyout',str(root/'tls'/f'{prefix}.key'),'-out',str(root/'tls'/f'{prefix}.crt'))
        run('sudo','chown','-R','568:568',str(root))
        run('docker','network','create','--internal',network)
        def start(name,image,options,command=()):
            containers.append(name)
            return run('docker','run','-d','--name',name,'--network',network,*options,image,*command)
        def exec_worker(code):return run('docker','exec','--user','568:568',identity+'-worker','python','-c',code,check=False)
        try:
            api_code="import ssl;from http.server import HTTPServer,BaseHTTPRequestHandler;s=HTTPServer(('0.0.0.0',8443),BaseHTTPRequestHandler);c=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);c.load_cert_chain('/fixture/untrusted.crt','/fixture/untrusted.key');s.socket=c.wrap_socket(s.socket,server_side=True);s.serve_forever()"
            start(identity+'-api','plexconfigcontrol:panel-check',['--network-alias','api-fixture','--read-only','--cap-drop','ALL','--user','568:568','--mount',f'type=bind,src={root}/tls,dst=/fixture,readonly','--entrypoint','python'],['-c',api_code])
            for attempt in range(20):
                listening=run('docker','exec',identity+'-api','python','-c',"import socket;socket.create_connection(('127.0.0.1',8443),timeout=2).close()",check=False)
                if listening.returncode==0:break
                time.sleep(.2)
            else:raise AssertionError('TLS fixture server did not start')
            capabilities=[arg for cap in ('SETUID','SETGID','SETPCAP','CHOWN','DAC_OVERRIDE','FOWNER','FSETID') for arg in ('--cap-add',cap)]
            worker_options=['--read-only','--tmpfs','/tmp','--security-opt','no-new-privileges:true','--cap-drop','ALL',*capabilities]
            for source,target in (('state','/var/lib/plexconfigcontrol'),('archives','/srv/archives'),('config','/srv/plex')):
                worker_options+=['--mount',f'type=bind,src={root}/{source},dst={target}']
            worker_options+=['--mount',f'type=bind,src={root}/key,dst=/run/pcc-secrets/truenas-key,readonly','--mount',f'type=bind,src={root}/tls/trusted.crt,dst=/run/pcc-secrets/truenas-ca,readonly']
            command=['--panel-uid','568','--state','/var/lib/plexconfigcontrol','--archives','/srv/archives','--config-mount','/srv/plex','--host-config','/mnt/fixture/plex','--dataset','fixture/plex','--socket','/var/lib/plexconfigcontrol/execution.sock','--truenas-url','wss://api-fixture:8443/api/current','--api-username','plexconfigcontrol','--api-key-file','/run/pcc-secrets/truenas-key','--ca-file','/run/pcc-secrets/truenas-ca','--plex-sqlite','/usr/local/bin/pcc-plex-sqlite','--sqlite-version',os.environ['PLEX_SQLITE_VERSION']]
            start(identity+'-worker','plexconfigcontrol:worker-check',worker_options,command)
            panel_options=['--read-only','--tmpfs','/tmp','--security-opt','no-new-privileges:true','--cap-drop','ALL',
                '--mount',f'type=bind,src={root}/state,dst=/var/lib/plexconfigcontrol',
                '--mount',f'type=bind,src={root}/archives,dst=/srv/archives,readonly',
                '-e','PCC_PUBLIC_HOST=localhost','-e','PCC_ARCHIVE_DIRECTORY=/srv/archives',
                '-e','PCC_EXECUTION_SOCKET=/var/lib/plexconfigcontrol/execution.sock','-e','PCC_EXECUTION_UID=568',
                '-e','PCC_BOOTSTRAP_VERIFIER='+password_verifier('dummy-ci-panel-password')]
            start(identity+'-panel','plexconfigcontrol:panel-check',panel_options)
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                result=run('docker','exec',identity+'-panel','python','-m','plexconfigcontrol.healthcheck',check=False)
                if result.returncode==0:break
                time.sleep(1)
            else:raise AssertionError('Panel/worker never became ready without trusted API TLS')
            code="""import ssl,http.client,json
context=ssl.create_default_context(cafile='/var/lib/plexconfigcontrol/tls/panel.crt')
def request(path,method='GET',data=None,cookie=None):
 c=http.client.HTTPSConnection('localhost',8443,context=context,timeout=20)
 headers={'Origin':'https://localhost:8443','X-PCC-Request':'1','Content-Type':'application/json'}
 if cookie:headers['Cookie']=cookie
 c.request(method,path,body=json.dumps(data) if data is not None else None,headers=headers)
 r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read());c.close();return result
status,headers,body=request('/api/login','POST',{'password':'dummy-ci-panel-password'})
assert status==200,(status,body)
cookie=headers['Set-Cookie'].split(';')[0]
status,_,body=request('/api/status',cookie=cookie)
result=json.loads(body)
assert status==200 and result['state']=='UNKNOWN' and result['error_code']=='TLS_UNTRUSTED',result
assert request('/healthz')[0]==200
assert request('/api/history',cookie=cookie)[0]==200
assert request('/assets/connection-notice.mjs')[0]==200
print('Actual container panel: ready, signed in, precise TLS error, history/static assets accessible: PASS')
"""
            verified=run('docker','exec',identity+'-panel','python','-c',code)
            print(verified.stdout.strip(),flush=True)
            result=exec_worker("from pathlib import Path;from plexconfigcontrol.execution_journal import ExecutionJournal;assert ExecutionJournal('/var/lib/plexconfigcontrol').current() is None;assert Path('/srv/plex/keep').read_text()=='Plex fixture';assert Path('/srv/archives/keep').read_text()=='archive fixture'")
            assert result.returncode==0,result.stderr
            print('Actual worker: local journal ready while API certificate is untrusted; Plex/archive fixtures unchanged: PASS',flush=True)
        except BaseException:
            for name in containers:
                print(name,run('docker','logs','--tail','40',name,check=False).stdout,flush=True)
            raise
        finally:
            for name in reversed(containers):run('docker','rm','-f',name,check=False)
            run('docker','network','rm',network,check=False)
            run('sudo','chown','-R',f'{os.getuid()}:{os.getgid()}',str(root))


if __name__=='__main__':main()
