"""WSGI JSON endpoints. Mount behind an HTTPS server; UI integration pending."""
import json
from http.cookies import SimpleCookie, CookieError
from .auth import Account
from .sessions import Sessions
from .settings import Settings
from .history import History
from .i18n import CATALOG
from .downloads import history_logs, MissingHistoryEvent
from .archive_store import ArchiveStore, Archive, ArchiveChanged
from .locking import OperationBusy
from dataclasses import asdict
from .plex import PlexStatus

class Web:
    def __init__(self,state_directory,archive_directory=None,truenas_api=None):
        self.plex=PlexStatus(truenas_api) if truenas_api is not None else None
        self.archives=ArchiveStore(archive_directory,state_directory) if archive_directory else None
        self.account=Account(state_directory)
        self.sessions=Sessions(state_directory)
        self.settings=Settings(state_directory)
        self.history=History(state_directory)

    def __call__(self,environ,start_response):
        headers=[('Content-Type','application/json; charset=utf-8'),
                 ('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]
        def respond(code,data):
            body=json.dumps(data,ensure_ascii=False).encode()
            start_response(code,headers+[('Content-Length',str(len(body)))])
            return [body]
        method=environ.get('REQUEST_METHOD','GET')
        path=environ.get('PATH_INFO','/')
        cookie=SimpleCookie()
        try: cookie.load(environ.get('HTTP_COOKIE',''))
        except CookieError: return respond('400 Bad Request',{'error':'Invalid cookie'})
        token=cookie['pcc_session'].value if 'pcc_session' in cookie else None
        data={}
        if method=='POST':
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
                return respond('401 Unauthorized',result)
            if token: self.sessions.logout(token)
            token,csrf=self.sessions.create()
            headers.append(('Set-Cookie','pcc_session='+token+'; Path=/; Secure; HttpOnly; SameSite=Strict'))
            return respond('200 OK',{'authenticated':True,'csrf':csrf})
        if not self.sessions.authenticated(token):
            return respond('401 Unauthorized',{'error':'Sign in required'})
        if method=='POST' and not self.sessions.check_csrf(token,environ.get('HTTP_X_CSRF_TOKEN')):
            return respond('403 Forbidden',{'error':'Invalid CSRF token'})
        if path=='/api/account/password' and method=='POST':
            current=data.get('current_password')
            new=data.get('new_password')
            confirm=data.get('confirm_new_password')
            if (not all(isinstance(p,str) and 0<len(p)<=4096 for p in (current,new,confirm))):
                return respond('400 Bad Request',{'error':'All password fields are required'})
            if new!=confirm:
                return respond('400 Bad Request',{'error':'New passwords do not match'})
            if not self.account.change_password(current,new):
                return respond('403 Forbidden',{'error':'Current password rejected or account blocked'})
            self.sessions.revoke_all()
            headers.append(('Set-Cookie','pcc_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict'))
            self.history.add('PASSWORD_CHANGE','SUCCESS','Panel password changed. All sessions revoked.')
            return respond('200 OK',{'changed':True,'sign_in_required':True})
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
        if path=='/api/status' and method=='GET':
            status=self.plex.read() if self.plex else {
                'state':'UNKNOWN','available':False,'restore_allowed':False,'checked_at':None}
            return respond('200 OK',status)
        if path=='/api/archives' and method=='GET':
            if self.archives is None:
                return respond('503 Service Unavailable',{'error':'Archive location is not configured'})
            try:
                return respond('200 OK',[asdict(item) for item in self.archives.list()])
            except OSError:
                return respond('503 Service Unavailable',{'error':'Archive location is unavailable'})
        if path=='/api/archives/delete' and method=='POST':
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
                    if not isinstance(item['name'],str) or any(
                            type(item[k]) is not int or item[k]<0
                            for k in ('size','device','inode','modified_ns')):
                        raise ValueError('Invalid identity')
                    items.append(Archive(**item))
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
        if path=='/api/history' and method=='GET':
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
