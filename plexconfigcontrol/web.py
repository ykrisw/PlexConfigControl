"""Development panel and WSGI JSON endpoints. Mount behind an HTTPS server."""
import json
from importlib.resources import files
from http.cookies import SimpleCookie, CookieError
from .auth import Account
from .sessions import Sessions, SessionChanged
from .settings import Settings
from .history import History
from .archive_discovery import ArchiveDiscovery
from .i18n import CATALOG
from .downloads import history_logs, MissingHistoryEvent
from .archive_store import ArchiveStore, Archive, ArchiveChanged
from .locking import OperationBusy
from dataclasses import asdict
from .plex import PlexStatus
from .progress import Progress
from .state import StateStore
from dataclasses import asdict as operation_dict
from .publication_intent import describe as describe_publication
from .backup_plan import plan_backup
from .restore_validation import RestoreValidation
from .archives import InvalidArchive
from .operations import OperationDenied
from .restore_readiness import restore_readiness
from .recovery_status import recovery_status
from .integration_diagnostics import inspect_integration
from .outcome import describe_outcome
from .profile_photo import ProfilePhoto,InvalidPhoto,PhotoChanged,MAX_UPLOAD

class Web:
    def __init__(self,state_directory,archive_directory=None,truenas_api=None,*,archive_deletion_enabled=True,archive_logs_enabled=True,recovery_inspector=None):
        self.state_directory=state_directory
        self.recovery_inspector=recovery_inspector
        self.operation_store=StateStore(state_directory)
        self.progress=Progress(state_directory)
        self.plex=PlexStatus(truenas_api) if truenas_api is not None else None
        self.truenas_api=truenas_api
        self.archives=ArchiveStore(archive_directory,state_directory) if archive_directory else None
        self.account=Account(state_directory)
        self.sessions=Sessions(state_directory,self.account)
        self.settings=Settings(state_directory)
        self.history=History(state_directory)
        self.discovery=ArchiveDiscovery(archive_directory,state_directory,self.history,
            permanent_logs=archive_logs_enabled) if archive_directory else None
        self.archive_deletion_enabled=archive_deletion_enabled
        self.photo=ProfilePhoto(state_directory)

    def __call__(self,environ,start_response):
        headers=[('Content-Type','application/json; charset=utf-8'),
                 ('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]
        def respond(code,data):
            body=json.dumps(data,ensure_ascii=False).encode()
            start_response(code,headers+[('Content-Length',str(len(body)))])
            return [body]
        method=environ.get('REQUEST_METHOD','GET')
        path=environ.get('PATH_INFO','/')
        assets={'/assets/panel-client.mjs':'panel-client.mjs',
                '/assets/restore-panel.mjs':'restore-panel.mjs',
                '/assets/restore-messages.mjs':'restore-messages.mjs',
                '/assets/restore-view.mjs':'restore-view.mjs',
                '/assets/restore-view.css':'restore-view.css',
                '/assets/panel-shell.mjs':'panel-shell.mjs',
                '/assets/panel-layout.css':'panel-layout.css',
                '/assets/panel-app.css':'panel-app.css',
                '/assets/panel-app.mjs':'panel-app.mjs',
                '/assets/dashboard-controller.mjs':'dashboard-controller.mjs',
                '/assets/dashboard-view.mjs':'dashboard-view.mjs',
                '/assets/photo-controller.mjs':'photo-controller.mjs',
                '/assets/history-controller.mjs':'history-controller.mjs',
                '/assets/history-view.mjs':'history-view.mjs',
                '/assets/settings-controller.mjs':'settings-controller.mjs',
                '/assets/integration-controller.mjs':'integration-controller.mjs',
                '/assets/integration-view.mjs':'integration-view.mjs',
                '/assets/settings-view.mjs':'settings-view.mjs',
                '/assets/recovery-view.mjs':'recovery-view.mjs',
                '/assets/recovery-controller.mjs':'recovery-controller.mjs',
                '/assets/operation-outcome.mjs':'operation-outcome.mjs',
                '/assets/backup-controller.mjs':'backup-controller.mjs',
                '/assets/backup-view.mjs':'backup-view.mjs',
                '/assets/approved-appearance.css':'approved-appearance.css'}
        if method=='GET' and path=='/':
            body=files('plexconfigcontrol').joinpath('static/index.html').read_bytes()
            start_response('200 OK',[
                ('Content-Type','text/html; charset=utf-8'),
                ('Content-Length',str(len(body))),('Cache-Control','no-store'),
                ('X-Content-Type-Options','nosniff'),('X-Frame-Options','DENY'),
                ('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; "
                 "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")])
            return [body]
        if method=='GET' and path in assets:
            body=files('plexconfigcontrol').joinpath('static/'+assets[path]).read_bytes()
            start_response('200 OK',[
                ('Content-Type',('text/css' if path.endswith('.css') else 'text/javascript')+'; charset=utf-8'),
                ('Content-Length',str(len(body))),('Cache-Control','no-store'),
                ('X-Content-Type-Options','nosniff')])
            return [body]
        cookie=SimpleCookie()
        try: cookie.load(environ.get('HTTP_COOKIE',''))
        except CookieError: return respond('400 Bad Request',{'error':'Invalid cookie'})
        token=cookie['pcc_session'].value if 'pcc_session' in cookie else None
        data={}
        photo_upload=path=='/api/account/photo' and method=='POST'
        if method=='POST' and not photo_upload:
            if not environ.get('CONTENT_TYPE','').split(';')[0]=='application/json':
                return respond('415 Unsupported Media Type',{'error':'JSON required'})
            try:
                length=int(environ.get('CONTENT_LENGTH') or 0)
                if not 0 < length <= 16384: raise ValueError()
                data=json.loads(environ['wsgi.input'].read(length))
                if not isinstance(data,dict): raise ValueError()
            except (ValueError,UnicodeError):
                return respond('400 Bad Request',{'error':'Invalid request body'})
        if path=='/api/login' and method=='POST':
            # Require a custom header so cross-origin HTML forms cannot log in.
            if environ.get('HTTP_X_PCC_REQUEST')!='1':
                return respond('403 Forbidden',{'error':'Request header required'})
            password=data.get('password')
            if not isinstance(password,str) or len(password)>4096:
                return respond('400 Bad Request',{'error':'Invalid password field'})
            try: result=self.account.login(password)
            except RuntimeError:
                return respond('503 Service Unavailable',{'error':'Installation not initialized'})
            if not result['authenticated']:
                blocked=result['blocked_until']
                self.history.add('LOGIN','FAILED',
                    'Sign-in rejected. Remaining attempts: '+str(result['remaining'])+
                    '. Blocked until (Unix UTC): '+str(blocked)+'.')
                return respond('401 Unauthorized',result)
            try:
                if token: self.sessions.logout(token)
                token,csrf=self.sessions.create(expected_stamp=result['credential_stamp'])
            except SessionChanged:
                return respond('409 Conflict',{'error':'Credentials changed during sign-in. Try again.'})
            except Exception:
                return respond('503 Service Unavailable',{'error':'Sign-in could not be confirmed'})
            headers.append(('Set-Cookie','pcc_session='+token+'; Path=/; Secure; HttpOnly; SameSite=Strict'))
            return respond('200 OK',{'authenticated':True,'csrf':csrf})
        if not self.sessions.authenticated(token):
            return respond('401 Unauthorized',{'error':'Sign in required'})
        if method=='POST' and not self.sessions.check_csrf(token,environ.get('HTTP_X_CSRF_TOKEN')):
            return respond('403 Forbidden',{'error':'Invalid CSRF token'})
        if path=='/api/account/photo/status' and method=='GET':
            try: return respond('200 OK',self.photo.status())
            except OSError: return respond('503 Service Unavailable',{'error':'Profile photo storage is unavailable'})
        if path=='/api/account/photo' and method=='GET':
            try: image=self.photo.read()
            except OSError: return respond('503 Service Unavailable',{'error':'Profile photo storage is unavailable'})
            if image is None: return respond('404 Not Found',{'error':'No profile photo'})
            start_response('200 OK',[('Content-Type','image/png'),('Content-Length',str(len(image))),
                ('Cache-Control','private, no-store'),('X-Content-Type-Options','nosniff')])
            return [image]
        if photo_upload:
            if environ.get('CONTENT_TYPE','').split(';')[0]!='application/octet-stream':
                return respond('415 Unsupported Media Type',{'error':'Upload the image file directly'})
            try:
                length=int(environ.get('CONTENT_LENGTH') or 0)
                if not 0<length<=MAX_UPLOAD: return respond('413 Content Too Large',{'error':'Choose a JPEG or PNG photo up to 5 MiB'})
            except ValueError:
                return respond('400 Bad Request',{'error':'Invalid upload length'})
            payload=environ['wsgi.input'].read(length)
            if len(payload)!=length: return respond('400 Bad Request',{'error':'Incomplete photo upload'})
            try: result=self.photo.upload(payload)
            except InvalidPhoto as error: return respond('422 Unprocessable Entity',{'error':str(error)})
            except OSError: return respond('503 Service Unavailable',{'error':'Profile photo storage is unavailable'})
            self.history.add('PROFILE_PHOTO','SUCCESS','Profile photo updated.')
            return respond('200 OK',result)
        if path=='/api/account/photo/remove' and method=='POST':
            if data.get('confirmed') is not True: return respond('400 Bad Request',{'error':'Confirm profile photo removal'})
            revision=data.get('revision')
            if not isinstance(revision,str) or len(revision)!=64 or any(c not in '0123456789abcdef' for c in revision):
                return respond('400 Bad Request',{'error':'Confirm the displayed profile photo'})
            try: result=self.photo.remove(confirmed=True,expected_revision=revision)
            except PhotoChanged as error: return respond('409 Conflict',{'error':str(error)})
            except OSError: return respond('503 Service Unavailable',{'error':'Profile photo storage is unavailable'})
            self.history.add('PROFILE_PHOTO','SUCCESS','Profile photo removed.')
            return respond('200 OK',result)
        if path=='/api/session' and method=='GET':
            csrf=self.sessions.csrf_for(token)
            if csrf is None:
                return respond('401 Unauthorized',{'error':'Sign in required'})
            return respond('200 OK',{'authenticated':True,'csrf':csrf})
        if path=='/api/capabilities' and method=='GET':
            return respond('200 OK',{'backup_create':False,'backup_overwrite':False,
                'restore_execute':False,'snapshot_management':False,
                'archive_delete':self.archives is not None and self.archive_deletion_enabled,
                'archive_validation':self.archives is not None})
        if path=='/api/account/password' and method=='POST':
            current=data.get('current_password')
            new=data.get('new_password')
            confirm=data.get('confirm_new_password')
            if (not all(isinstance(p,str) and 0<len(p)<=4096 for p in (current,new,confirm))):
                return respond('400 Bad Request',{'error':'All password fields are required'})
            if new!=confirm:
                return respond('400 Bad Request',{'error':'New passwords do not match'})
            try: changed=self.account.change_password(current,new)
            except Exception:
                return respond('503 Service Unavailable',{'error':'Password change could not be confirmed. Sign in again before retrying.'})
            if not changed:
                return respond('403 Forbidden',{'error':'Current password rejected or account blocked'})
            # Credential binding already invalidates all prior sessions, even
            # when deleting obsolete session rows fails on storage.
            cleanup_pending=False
            try: self.sessions.revoke_all()
            except Exception: cleanup_pending=True
            headers.append(('Set-Cookie','pcc_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict'))
            history_recorded=True
            try: self.history.add('PASSWORD_CHANGE','SUCCESS','Panel password changed. Prior credential-bound sessions invalidated.')
            except Exception: history_recorded=False
            result={'changed':True,'sign_in_required':True}
            if cleanup_pending: result['session_cleanup_pending']=True
            if not history_recorded: result['history_recorded']=False
            return respond('200 OK',result)
        if path=='/api/logout' and method=='POST':
            self.sessions.logout(token)
            headers.append(('Set-Cookie','pcc_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict'))
            return respond('200 OK',{'authenticated':False})
        if path=='/api/settings' and method in ('GET','POST'):
            try: prefs=self.settings.update(**data) if method=='POST' else self.settings.read()
            except (ValueError,TypeError): return respond('400 Bad Request',{'error':'Invalid settings'})
            return respond('200 OK',prefs)
        if path=='/api/translations' and method=='GET':
            return respond('200 OK',CATALOG[self.settings.read()['language']])
        if path=='/api/operation' and method=='GET':
            with self.operation_store.transaction() as operation:
                state=operation_dict(operation)
                state['outcome']=describe_outcome(operation.outcome,operation.kind) if operation.kind in ('BACKUP','RESTORE') else None
            return respond('200 OK',{'operation':state,'progress':self.progress.read(),
                                    'publication':describe_publication(self.state_directory),
                                    'archive_discovery':self.discovery.status() if self.discovery else None})
        if path=='/api/recovery' and method=='GET':
            try:
                return respond('200 OK',recovery_status(self.operation_store,self.recovery_inspector))
            except OperationBusy:
                return respond('409 Conflict',{'error':'Another operation or recovery must finish'})
            except Exception:
                return respond('503 Service Unavailable',{'error':'Recovery status could not be confirmed'})
        if path=='/api/integration' and method=='GET':
            return respond('200 OK',inspect_integration(self.operation_store,self.archives,
                                                       self.plex,self.recovery_inspector))
        if path=='/api/status' and method=='GET':
            status=self.plex.read() if self.plex else {
                'state':'UNKNOWN','available':False,'restore_allowed':False,'checked_at':None}
            return respond('200 OK',status)
        if path=='/api/backup/plan' and method=='GET':
            if self.archives is None:
                return respond('503 Service Unavailable',{'error':'Archive location is not configured'})
            try:
                plan=plan_backup(self.archives.directory,self.state_directory)
            except OperationBusy:
                return respond('409 Conflict',{'error':'Another operation or recovery must finish'})
            except OSError:
                return respond('503 Service Unavailable',{'error':'Archive location is unavailable'})
            if plan['existing_archive'] is not None:
                plan['existing_archive']=archive_wire(plan['existing_archive'])
            return respond('200 OK',plan)
        if path=='/api/restore/readiness' and method=='GET':
            try:
                result=restore_readiness(self.operation_store,self.state_directory,self.truenas_api,
                                        self.archives.directory if self.archives else None)
            except OperationBusy:
                return respond('409 Conflict',{'error':'Another operation is running'})
            return respond('200 OK',result)
        if path in ('/api/restore/validate','/api/restore/cancel') and method=='POST':
            if self.archives is None:
                return respond('503 Service Unavailable',{'error':'Archive location is not configured'})
            service=RestoreValidation(self.archives.directory,self.state_directory,
                                      self.operation_store,self.history)
            try:
                if path=='/api/restore/cancel':
                    service.cancel()
                    return respond('200 OK',{'cancelled':True})
                if data.get('background') is True:
                    service.start_background(data.get('archive'))
                    return respond('202 Accepted',{'accepted':True,
                        'status_url':'/api/operation'})
                if 'background' in data and data['background'] is not False:
                    return respond('400 Bad Request',{'error':'Invalid background option'})
                # Retained for local diagnostics; the UI should use background.
                result=service.validate(data.get('archive'))
                return respond('200 OK',result)
            except (OperationBusy,OperationDenied):
                return respond('409 Conflict',{'error':'Another operation or recovery must finish'})
            except InvalidArchive as error:
                return respond('422 Unprocessable Entity',{'error':str(error),'validation':'FAILED'})
            except ValueError:
                return respond('400 Bad Request',{'error':'Choose a recognized backup archive'})
            except OSError:
                return respond('503 Service Unavailable',{'error':'Archive is unavailable or unreadable'})
        if path=='/api/archives' and method=='GET':
            if self.archives is None:
                return respond('503 Service Unavailable',{'error':'Archive location is not configured'})
            try:
                return respond('200 OK',[archive_wire(asdict(item)) for item in self.discovery.scan()])
            except OSError:
                return respond('503 Service Unavailable',{'error':'Archive location is unavailable'})
        if path=='/api/archives/delete' and method=='POST':
            if not self.archive_deletion_enabled:
                return respond('403 Forbidden',{'error':'Archive deletion is disabled in this installation'})
            if self.archives is None:
                return respond('503 Service Unavailable',{'error':'Archive location is not configured'})
            selected=data.get('archives')
            if (data.get('confirmed') is not True or not isinstance(selected,list)
                    or not selected or len(selected)>1000):
                return respond('400 Bad Request',{'error':'Select archives and confirm deletion'})
            try:
                items=[]
                for item in selected:
                    if not isinstance(item,dict) or set(item)!=set(Archive.__dataclass_fields__):
                        raise ValueError('Invalid identity')
                    if not isinstance(item['name'],str):
                        raise ValueError('Invalid identity')
                    items.append(Archive(name=item['name'],**{
                        key:archive_integer(item[key]) for key in ('size','device','inode','modified_ns')}))
                removed=self.archives.delete(items,confirmed=True)
            except (ValueError,TypeError):
                return respond('400 Bad Request',{'error':'Invalid archive selection'})
            except OperationBusy:
                return respond('409 Conflict',{'error':'Another operation is running'})
            except (ArchiveChanged,FileNotFoundError):
                return respond('409 Conflict',{'error':'Archive selection changed; refresh the list'})
            except OSError:
                # Some prior selected files may have been removed. Do not claim
                # batch atomicity; the UI must refresh after any deletion error.
                return respond('503 Service Unavailable',{'error':'Deletion incomplete; refresh archive list'})
            self.history.add('ARCHIVE_DELETE','SUCCESS',
                             'Deleted archives: '+', '.join(removed))
            return respond('200 OK',{'deleted':removed})
        if path=='/api/history/detail' and method=='POST':
            event_id=data.get('id')
            if type(event_id) is not int or event_id<=0:
                return respond('400 Bad Request',{'error':'Invalid event identity'})
            event=self.history.detail(event_id)
            if event is None:
                return respond('404 Not Found',{'error':'History event no longer exists'})
            return respond('200 OK',event)
        if path=='/api/history' and method=='GET':
            if self.discovery:
                try: self.discovery.scan()
                except OSError: pass  # Existing history stays available if the folder is offline.
            return respond('200 OK',self.history.list())
        if path=='/api/history/download' and method=='POST':
            try:
                name,content_type,body=history_logs(self.history,data.get('ids'))
            except MissingHistoryEvent:
                return respond('404 Not Found',{'error':'History event no longer exists'})
            except ValueError:
                return respond('400 Bad Request',{'error':'Invalid or oversized log selection'})
            start_response('200 OK',[
                ('Content-Type',content_type),('Content-Length',str(len(body))),
                ('Content-Disposition','attachment; filename="'+name+'"'),
                ('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')])
            return [body]
        if path=='/api/history/clear' and method=='POST':
            ids=data.get('ids')
            if (data.get('confirmed') is not True or not isinstance(ids,list)
                    or not ids or len(ids)>10000
                    or any(type(i) is not int or i<=0 for i in ids)):
                return respond('400 Bad Request',{'error':'Select entries and confirm deletion'})
            self.history.clear(ids)
            return respond('200 OK',{'cleared':ids})
        return respond('404 Not Found',{'error':'Not found'})


def archive_wire(item):
    # Nanosecond timestamps and ZFS inode IDs exceed JavaScript's exact integer
    # range. Transfer identities as decimal strings so confirmation round-trips.
    return {key:value if key=='name' else str(value) for key,value in item.items()}


def archive_integer(value):
    if type(value) is int and 0<=value<2**64:
        return value  # Retain compatibility with non-browser clients.
    if (isinstance(value,str) and 1<=len(value)<=20 and value.isascii()
            and value.isdecimal() and (value=='0' or not value.startswith('0'))
            and int(value)<2**64):
        return int(value)
    raise ValueError('Invalid archive identity number')
