"""Keep an existing NAS session active; never store passwords or TOTP codes."""
import json
import os
from pathlib import Path
import re
import stat
import threading
from .qnap_api import QnapLocalReadOnlyApi, QnapApiError, local_certificate_context


def remember(service):
    api,user=service.api,service.user
    token=getattr(api,'_session',None)
    if user is None or not isinstance(token,str) or not re.fullmatch('[A-Za-z0-9_-]{8,128}',token):return
    from .qnap_service import write_record
    write_record(service.owner/'qnap-session.json',{'username':user.pw_name,'sid':token})


def tick(service):
    from .qnap_service import administrator
    with service.mutex:
        if service.auth_busy:return
        path=service.owner/'qnap-session.json'
        api=service.api
        restoring=api is None
        try:
            if restoring:
                try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                except FileNotFoundError:return
                with os.fdopen(fd,'r') as stream:
                    info=os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077 or info.st_size>4096:raise ValueError('Invalid private session record')
                    record=json.load(stream)
                if set(record)!={'username','sid'} or not isinstance(record['sid'],str) or not re.fullmatch('[A-Za-z0-9_-]{8,128}',record['sid']):raise ValueError('Invalid private session record')
                user=administrator(record['username'])
                context,pin=local_certificate_context(Path('/etc/stunnel/stunnel.pem').read_text())
                api=QnapLocalReadOnlyApi(443,tls_context=context,certificate_sha256=pin)
                api._session=record['sid']
            api.snapshot_count(service.discover().volume_id)
            if restoring:service.api,service.user=api,user
            remember(service)
        except QnapApiError as error:
            if str(error) in {'QNAP_SESSION_EXPIRED','QNAP_LOGIN_REQUIRED'}:
                if service.api:service.api.forget_session()
                service.api=None;service.user=None
                path.unlink(missing_ok=True)
            # A temporary network failure must not discard the NAS session.
        except (OSError,ValueError,KeyError,TypeError):
            # No credentials, certificates, tokens or exception bodies in logs.
            return


def start(service):
    def loop():
        while True:
            try:tick(service)
            except Exception:pass
            threading.Event().wait(60)
    threading.Thread(target=loop,name='pcc-nas-session',daemon=True).start()
