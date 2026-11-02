"""WSGI JSON endpoints. Mount behind an HTTPS server; UI integration pending."""
import json
from http.cookies import SimpleCookie, CookieError
from .auth import Account
from .sessions import Sessions
from .settings import Settings
from .history import History
from .i18n import CATALOG

class Web:
    def __init__(self,state_directory):
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
        if path=='/api/history' and method=='GET':
            return respond('200 OK',self.history.list())
        if path=='/api/history/clear' and method=='POST':
            ids=data.get('ids')
            if (data.get('confirmed') is not True or not isinstance(ids,list)
                    or not ids or len(ids)>10000
                    or any(type(i) is not int or i<=0 for i in ids)):
                return respond('400 Bad Request',{'error':'Select entries and confirm deletion'})
            self.history.clear(ids)
            return respond('200 OK',{'cleared':ids})
        return respond('404 Not Found',{'error':'Not found'})
