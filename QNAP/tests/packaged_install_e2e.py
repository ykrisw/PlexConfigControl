"""Disposable CI only: exercise the actual packaged TLS server and service UID.

No NAS, host QPKG registration or Plex data is accessed. The package's own
root supervisor, private Python, unprivileged Gunicorn and IPC are exercised.
"""
import argparse
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import zlib


def fixture_supervisor(root,port):
    spec=importlib.util.spec_from_file_location('qa_native_launcher',root/'launcher.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.DEFAULT_PORT=port
    # Never call QNAP's global setcfg/getcfg on a test host.
    module.qpkg_setting=lambda field,value:None
    module.supervise()


def extract(package,destination):
    with package.open('rb') as source:
        header=source.read(32768).split(b'\nexit 1\n')[0]
        script=int(re.search(rb'^script_len=(\d+)$',header,re.M)[1])
        control=int(re.search(rb'expr \$script_len \+ (\d+)',header)[1])
        size=int(re.search(rb'^\s*data_len=(\d+)$',header,re.M)[1])
        source.seek(script)
        control_data=source.read(control)
        source.seek(script+control)
        data=source.read(size)
        if len(data)!=size:raise ValueError('Truncated QPKG')
    control_dir=destination/'.qa-control';control_dir.mkdir()
    with tarfile.open(fileobj=io.BytesIO(control_data),mode='r:*') as archive:
        archive.extractall(control_dir,filter='data')
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
        archive.extractall(destination,filter='data')


def png():
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00'+b'\xff\x00\x00'*2+b'\x00'+b'\x00\xff\x00'*2))+chunk(b'IEND',b'')


def audit(package,expected):
    digest=hashlib.sha256(package.read_bytes()).hexdigest()
    if expected and digest!=expected:raise ValueError('Package checksum mismatch')
    print('Package SHA-256:',digest,flush=True)
    with tempfile.TemporaryDirectory(prefix='pcc-native-qa-') as folder:
        outer=Path(folder);outer.chmod(0o755)
        root=outer/'PCC';root.mkdir(mode=0o755);extract(package,root)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        runtime_log=outer/'runtime.log'
        def start():
            stream=runtime_log.open('ab')
            process=subprocess.Popen([str(root/'python/bin/python3'),'-I','-S',str(Path(__file__).resolve()),'--supervise-fixture',str(root),str(port),'--supervise',str(root/'launcher.py')],stdout=stream,stderr=stream)
            stream.close();return process
        def stop(process):
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:process.wait(timeout=35)
                except subprocess.TimeoutExpired:process.kill();process.wait();raise RuntimeError('Supervisor did not stop cleanly')
            if process.returncode!=0:raise RuntimeError('Supervisor exited unsuccessfully')
        context=None
        def request(path='/',method='GET',data=None,body=None,cookie='',csrf='',content_type='application/json'):
            headers={'Origin':f'https://localhost:{port}','X-PCC-Request':'1'}
            if cookie:headers['Cookie']=cookie
            if csrf:headers['X-CSRF-Token']=csrf
            if data is not None:body=json.dumps(data).encode()
            if body is not None:headers['Content-Type']=content_type
            connection=http.client.HTTPSConnection('localhost',port,context=context,timeout=15)
            try:
                connection.request(method,path,body=body,headers=headers)
                response=connection.getresponse();return response.status,dict(response.getheaders()),response.read()
            finally:connection.close()
        def ready(process):
            nonlocal context
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('Packaged server stopped during startup')
                cert=root/'var/panel/tls/panel.crt'
                if cert.exists():
                    context=ssl.create_default_context(cafile=str(cert))
                    try:
                        if request('/healthz')[0]==200:return
                    except (OSError,ssl.SSLError):pass
                time.sleep(.2)
            raise RuntimeError('Packaged TLS server never became ready')
        process=start()
        try:
            ready(process)
            uid=json.loads((root/'var/owner/service.json').read_text())['uid']
            assert uid!=0
            status,_,body=request();assert status==200 and b'First-run setup' in body,(status,body[:200])
            print('Fresh first-run page served by unprivileged TLS worker: PASS',flush=True)
            token=(root/'var/panel/setup-token').read_text().strip()
            setup={'token':token,'password':'qa-password-only','confirmation':'qa-password-only','language':'pl','port':port}
            status,_,body=request('/setup','POST',setup);assert status==200,(status,body[:200])
            status,_,body=request();assert status==200 and b'pcc' in body.lower(),(status,body[:200])
            status,headers,body=request('/api/login','POST',{'password':'qa-password-only'})
            assert status==200,(status,body[:200])
            cookie=headers['Set-Cookie'].split(';')[0];csrf=json.loads(body)['csrf']
            for path in ('/api/session','/api/settings','/api/account/photo/status','/api/qnap/info','/api/history','/assets/panel-app.mjs','/assets/qnap-tools.mjs','/assets/restore-panel.mjs'):
                status,_,body=request(path,cookie=cookie,csrf=csrf);assert status==200,(path,status,body[:200])
            status,_,body=request('/api/account/photo','POST',body=png(),cookie=cookie,csrf=csrf,content_type='application/octet-stream')
            assert status==200,(status,body[:200])
            assert list((root/'var/owner/qnap-event-outbox').glob('*.json'))
            for path in (root/'var/panel').glob('*.sqlite3'):assert path.stat().st_uid==uid,path.name
            assert (root/'var/panel/profile-photo.lock').stat().st_uid==uid
            print('Setup, panel login, native IPC, static assets, profile upload and durable event queue: PASS',flush=True)
            stop(process);process=start();ready(process)
            status,_,body=request('/api/session',cookie=cookie);assert status==200,(status,body[:200])
            status,_,body=request('/api/account/photo/status',cookie=cookie);assert status==200 and json.loads(body)['present'] is True
            status,_,body=request('/api/login','POST',{'password':'wrong-fixture-password'})
            assert status==401,(status,body[:200])
            photo_status=json.loads(request('/api/account/photo/status',cookie=cookie)[2])
            status,_,body=request('/api/account/photo/remove','POST',{'confirmed':True,'revision':photo_status['revision']},cookie=cookie,csrf=csrf)
            assert status==200 and json.loads(body)['present'] is False,(status,body[:200])
            status,_,body=request('/api/settings','POST',{'theme':'Dark','language':'en','timezone':'UTC'},cookie=cookie,csrf='invalid-csrf')
            assert status==403,(status,body[:200])
            status,_,body=request('/api/settings','POST',{'theme':'Dark','language':'en','timezone':'UTC'},cookie=cookie,csrf=csrf)
            assert status==200 and json.loads(body)['theme']=='Dark',(status,body[:200])
            status,_,body=request('/api/account/password','POST',{'current_password':'qa-password-only','new_password':'qa-password-next','confirm_new_password':'qa-password-next'},cookie=cookie,csrf=csrf)
            assert status==200 and json.loads(body).get('history_recorded',True),(status,body[:200])
            assert request('/api/session',cookie=cookie)[0]==401
            status,headers,body=request('/api/login','POST',{'password':'qa-password-next'})
            assert status==200,(status,body[:200])
            cookie=headers['Set-Cookie'].split(';')[0];csrf=json.loads(body)['csrf']
            status,_,body=request('/api/history',cookie=cookie)
            assert status==200
            ids=[row['id'] for row in json.loads(body)]
            assert ids
            events_before=list((root/'var/owner/qnap-event-outbox').glob('*.json'))
            status,_,body=request('/api/history/clear','POST',{'ids':ids,'confirmed':True},cookie=cookie,csrf=csrf)
            assert status==200,(status,body[:200])
            assert sorted((root/'var/owner/qnap-event-outbox').glob('*.json'))==sorted(events_before)
            for event in events_before:
                event_text=event.read_text()
                assert 'qa-password-only' not in event_text and 'qa-password-next' not in event_text
            status,_,body=request('/api/logout','POST',{},cookie=cookie,csrf=csrf)
            assert status==200 and request('/api/session',cookie=cookie)[0]==401
            print('Restart, profile removal, settings, CSRF, password change, history clear and explicit logout: PASS',flush=True)
            # Generate and run the real pinned QDK uninstaller, confined to this fixture.
            control=root/'.qa-control'
            qdk=(root/'build-sources/qinstall.sh').read_text()
            function=re.search(r'(?ms)^create_uninstall_script\(\)\{.*?^\}',qdk).group()
            for name in ('init','startup','shutdown','icons','bin'):(outer/name).mkdir()
            which=outer/'bin/which';which.write_text('#!/bin/sh\nexit 1\n');which.chmod(0o755)
            import shlex
            values={'SYS_QPKG_DIR':str(root),'SYS_INIT_DIR':str(outer/'init'),
                    'SYS_STARTUP_DIR':str(outer/'startup'),'SYS_SHUTDOWN_DIR':str(outer/'shutdown'),
                    'SYS_RSS_IMG_DIR':str(outer/'icons'),'QPKG_SERVICE_PROGRAM':'PCC.sh','QPKG_NAME':'PCC',
                    'CMD_CAT':'/bin/cat','CMD_CHMOD':'/bin/chmod','CMD_RM':'/bin/rm',
                    'CMD_FIND':'/usr/bin/find','CMD_XARGS':'/usr/bin/xargs','CMD_MKDIR':'/bin/mkdir',
                    'CMD_SLEEP':'/bin/true','CMD_SYNC':'/bin/true'}
            script='\n'.join(key+'='+shlex.quote(value) for key,value in values.items())+'\n'+function+'\ncreate_uninstall_script\n'
            environment=dict(os.environ,PATH=str(outer/'bin')+':/usr/bin:/bin')
            subprocess.run(['bash','-c',script],cwd=control,env=environment,check=True)
            uninstall=root/'.uninstall.sh'
            assert '$SYS_QPKG_DIR' not in uninstall.read_text()
            # Refuse removal while a recorded operation is active, preserving all files.
            jobs=root/'var/owner/qnap-jobs';jobs.mkdir(exist_ok=True)
            identifier='a'*32;pointer=root/'var/owner/qnap-current.json';job=jobs/(identifier+'.json')
            pointer.write_text(json.dumps({'request_id':identifier}));pointer.chmod(0o600)
            job.write_text(json.dumps({'state':'RUNNING'}));job.chmod(0o600)
            result=subprocess.run(['sh',str(uninstall)],env=environment,capture_output=True)
            assert result.returncode!=0 and (root/'launcher.py').exists(),result.stderr
            assert process.poll() is None and request('/')[0]==200
            pointer.unlink();job.unlink()
            untouched=[]
            for name in ('PlexData','Archives'):
                directory=outer/name;directory.mkdir();keep=directory/'keep';keep.write_text(name);untouched.append(keep)
            subprocess.run(['sh',str(uninstall)],env=environment,check=True)
            process.wait(timeout=35)
            assert process.returncode==0 and not root.exists()
            assert all(path.read_text()==path.parent.name for path in untouched)
            with socket.socket() as released:
                released.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                released.bind(('127.0.0.1',port))
            print('Actual QDK uninstall: active-operation refusal, stopped service, removed app tree, released port, preserved Plex and archives: PASS',flush=True)
            root.mkdir(mode=0o755);extract(package,root);process=start();ready(process)
            assert request('/')[0]==200 and b'First-run setup' in request('/')[2]
            assert (root/'var/panel/setup-token').read_text().strip()!=token
            assert not (root/'var/panel/setup-complete.json').exists()
            print('Clean reinstall creates fresh setup and new token: PASS',flush=True)

        except BaseException:
            print(runtime_log.read_text(errors='replace')[-16000:],flush=True)
            raise
        finally:
            if process.poll() is None:stop(process)
    print('FULL PACKAGED FRESH-INSTALL TLS/UID/IPC AUDIT: PASS',flush=True)


if __name__=='__main__':
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.geteuid()!=0 or Path('/sbin/getcfg').exists():
        raise SystemExit('Run only as root on a disposable GitHub Actions Linux runner, never on a NAS.')
    if len(sys.argv)==6 and sys.argv[1]=='--supervise-fixture':fixture_supervisor(Path(sys.argv[2]),int(sys.argv[3]))
    else:
        parser=argparse.ArgumentParser();parser.add_argument('package',type=Path);parser.add_argument('--expected-sha256');args=parser.parse_args()
        audit(args.package.resolve(),args.expected_sha256)
