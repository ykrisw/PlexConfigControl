"""Run only on a disposable Docker CI runner, never on the user's NAS."""
import http.client
import io
import json
import os
import ssl
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from plexconfigcontrol.installation import password_verifier
from PIL import Image


def docker(*args,**kwargs):
    return subprocess.check_output(['docker',*args],text=True,**kwargs).strip()


def main():
    name='pcc-smoke-'+uuid.uuid4().hex[:12]
    volume=name+'-state'
    password='ci-test-only-password'
    environment=dict(os.environ,PCC_BOOTSTRAP_VERIFIER=password_verifier(password))
    docker('volume','create',volume)
    try:
        docker('run','-d','--name',name,'--read-only','--cap-drop=ALL',
               '--security-opt=no-new-privileges:true','--tmpfs','/tmp:rw,noexec,nosuid,size=64m',
               '-p','127.0.0.1::8443','-v',volume+':/var/lib/plexconfigcontrol',
               '-e','PCC_PUBLIC_HOST=127.0.0.1','-e','PCC_BOOTSTRAP_VERIFIER',
               'plexconfigcontrol:test',env=environment)
        port=int(json.loads(docker('inspect',name))[0]['NetworkSettings']['Ports']['8443/tcp'][0]['HostPort'])
        with tempfile.TemporaryDirectory() as temporary:
            cert=Path(temporary)/'panel.crt'
            for _ in range(60):
                result=subprocess.run(['docker','cp',name+':/var/lib/plexconfigcontrol/tls/panel.crt',str(cert)],capture_output=True)
                if result.returncode==0: break
                time.sleep(.5)
            else: raise RuntimeError('TLS identity was not created')
            original=cert.read_bytes()
            context=ssl.create_default_context(cafile=str(cert))
            def request(path,method='GET',body=None,session=None,csrf=None,raw=None):
                connection=http.client.HTTPSConnection('127.0.0.1',port,context=context,timeout=5)
                headers={}
                if raw is not None:headers['Content-Type']='application/octet-stream'
                elif body is not None: headers['Content-Type']='application/json'
                if path=='/api/login': headers['X-PCC-Request']='1'
                if session: headers['Cookie']=session
                if csrf: headers['X-CSRF-Token']=csrf
                connection.request(method,path,raw if raw is not None else json.dumps(body) if body is not None else None,headers)
                response=connection.getresponse(); data=response.read()
                result=(response.status,dict(response.getheaders()),data)
                connection.close(); return result
            def wait_ready():
                for _ in range(60):
                    try:
                        if request('/healthz')[0]==200: return
                    except (OSError,http.client.HTTPException): pass
                    time.sleep(.5)
                raise RuntimeError('Container did not become ready')
            wait_ready()
            assert request('/')[0]==200
            assert request('/api/history')[0]==401
            status,headers,data=request('/api/login','POST',{'password':password})
            assert status==200
            session=headers['Set-Cookie'].split(';')[0];csrf=json.loads(data)['csrf']
            capabilities=json.loads(request('/api/capabilities',session=session)[2])
            assert all(capabilities[key] is False for key in ('backup_create','backup_overwrite','restore_execute','snapshot_management','archive_delete'))
            assert json.loads(request('/api/status',session=session)[2])['state']=='UNKNOWN'
            for path in ('/api/backup/start','/api/restore/execute','/api/archives/delete','/api/snapshots/delete'):
                assert request(path,'POST',{},session,csrf)[0]==403
            assert request('/api/settings','POST',{'theme':'Dark','language':'pl'},session,csrf)[0]==200
            uploaded=io.BytesIO();Image.new('RGB',(32,24),'blue').save(uploaded,format='PNG')
            status,_,data=request('/api/account/photo','POST',session=session,csrf=csrf,raw=uploaded.getvalue())
            assert status==200;photo_revision=json.loads(data)['revision']
            status,headers,photo=request('/api/account/photo',session=session)
            assert status==200 and headers['Content-Type']=='image/png' and photo.startswith(b'\x89PNG')
            docker('restart',name)
            # Docker can allocate a different random host port after restart.
            port=int(json.loads(docker('inspect',name))[0]['NetworkSettings']['Ports']['8443/tcp'][0]['HostPort'])
            wait_ready()
            status,_,data=request('/api/settings',session=session)
            assert status==200 and json.loads(data)['theme']=='Dark' and json.loads(data)['language']=='pl'
            assert request('/api/account/photo',session=session)[2]==photo
            assert request('/api/account/photo/remove','POST',{'confirmed':True,'revision':'0'*64},session,csrf)[0]==409
            assert request('/api/account/photo/remove','POST',{'confirmed':True,'revision':photo_revision},session,csrf)[0]==200
            assert request('/api/account/photo',session=session)[0]==404
            docker('cp',name+':/var/lib/plexconfigcontrol/tls/panel.crt',str(cert))
            assert cert.read_bytes()==original
            assert request('/api/logout','POST',{},session,csrf)[0]==200
            assert request('/api/session',session=session)[0]==401
            assert docker('exec',name,'python','-m','plexconfigcontrol.healthcheck')==''
        print('Container HTTPS, auth, session/settings/photo persistence and disabled host operations: OK')
        return 0
    except BaseException:
        # Logs contain no test secrets; the runtime never prints credentials.
        subprocess.run(['docker','logs','--tail','50',name],check=False)
        raise
    finally:
        subprocess.run(['docker','rm','-f',name],check=False,stdout=subprocess.DEVNULL)
        subprocess.run(['docker','volume','rm',volume],check=False,stdout=subprocess.DEVNULL)


if __name__=='__main__': raise SystemExit(main())
