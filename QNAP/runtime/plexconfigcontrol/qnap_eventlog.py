"""Persist fixed panel-event messages in the selected Logs folder via the worker."""
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from datetime import datetime, timezone

KINDS={'PROFILE_PHOTO','PASSWORD_CHANGE','LOGIN','LOGOUT'}

class LoggedPanelHistory:
    def __init__(self,history,client):self.history,self.client=history,client
    def __getattr__(self,name):return getattr(self.history,name)
    def add(self,kind,status,log,archive=None):
        if kind in KINDS:
            action='removed' if kind=='PROFILE_PHOTO' and log=='Profile photo removed.' else 'updated' if kind=='PROFILE_PHOTO' else 'recorded'
            self.client.request('panel_event',{'id':uuid.uuid4().hex,'kind':kind,'status':status,'action':action})
        return self.history.add(kind,status,log,archive)

def panel_event(service,data):
    if (not isinstance(data,dict) or set(data)!={'id','kind','status','action'}
        or not isinstance(data['id'],str) or not re.fullmatch('[0-9a-f]{32}',data['id'])
        or data['kind'] not in KINDS or data['status'] not in {'SUCCESS','FAILED','WARNING'}
        or data['action'] not in {'updated','removed','recorded'}):
        raise ValueError('Invalid panel event')
    with service.mutex:
        queue=service.owner/'qnap-event-outbox';queue.mkdir(mode=0o700,exist_ok=True)
        path=queue/(data['id']+'.json')
        record={**data,'created':datetime.now(timezone.utc).isoformat()}
        if not path.exists():
            from .qnap_service import write_record
            write_record(path,record)
        flush_events(service)
        return {'recorded':True,'pending':path.exists()}

def flush_events(service):
    queue=service.owner/'qnap-event-outbox'
    if not queue.exists() or not service.location.exists():return
    binding,folder=service._binding()
    directory=os.open(folder/'Logs',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        if [os.fstat(directory).st_dev,os.fstat(directory).st_ino]!=binding['logs_identity']:
            raise ValueError('Logs folder identity changed')
        for pending in sorted(queue.glob('*.json')):
            value=json.loads(pending.read_text())
            payload=(json.dumps(value,ensure_ascii=True,sort_keys=True)+'\n').encode()
            name='pcc-event-'+value['id']+'.log'
            try:fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
            except FileExistsError:
                fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
                with os.fdopen(fd,'rb') as stream:
                    if stream.read(len(payload)+1)!=payload:raise ValueError('Event log identity conflict')
            else:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(payload);stream.flush()
                    os.fchown(stream.fileno(),binding['uid'],binding['gid']);os.fsync(stream.fileno())
                os.fsync(directory)
            pending.unlink()
        fd=os.open(queue,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:os.close(directory)
