"""Authenticated QNAP routes; the web process has no NAS filesystem authority."""
import json
from http.cookies import SimpleCookie, CookieError
from urllib.parse import parse_qs
from .downloads import history_logs, MissingHistoryEvent

EVENT_BASE=1_000_000_000


class QnapWeb:
    GET={'/api/qnap/info':'info','/api/qnap/shares':'shares','/api/archives':'archives',
         '/api/integration':'integration','/api/backup/plan':'plan','/api/restore/readiness':'restore_readiness','/api/operation':'operation','/api/recovery':'recovery'}
    POST={'/api/qnap/auth':'auth','/api/qnap/configure':'configure','/api/qnap/recover':'recover','/api/qnap/restore-review':'restore_review',
          '/api/restore/validate':'restore_validate','/api/restore/cancel':'restore_cancel','/api/restore/execute':'restore_execute'}
    EXTRA={'/api/capabilities','/api/backup/start','/api/execution/status','/api/history',
           '/api/history/detail','/api/history/clear','/api/history/download','/api/restore/readiness'}

    def __init__(self,web,client):
        self.web,self.client=web,client
        from .qnap_eventlog import LoggedPanelHistory
        self.web.history=LoggedPanelHistory(self.web.history,client)

    @staticmethod
    def reply(start,code,data,headers=None):
        body=json.dumps(data,ensure_ascii=False).encode()
        start(code,[('Content-Type','application/json; charset=utf-8'),('Content-Length',str(len(body))),
                    ('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]+(headers or []))
        return [body]

    def __call__(self,environ,start):
        path=environ.get('PATH_INFO','/');method=environ.get('REQUEST_METHOD','GET')
        if path not in self.GET and path not in self.POST and path not in self.EXTRA:
            return self.web(environ,start)
        respond=lambda code,data:self.reply(start,code,data)
        try:
            cookie=SimpleCookie();cookie.load(environ.get('HTTP_COOKIE',''))
            token=cookie['pcc_session'].value if 'pcc_session' in cookie else None
        except CookieError:return respond('400 Bad Request',{'error':'Invalid cookie'})
        if not self.web.sessions.authenticated(token):return respond('401 Unauthorized',{'error':'Sign in required'})
        data={}
        if method=='POST':
            if not self.web.sessions.check_csrf(token,environ.get('HTTP_X_CSRF_TOKEN')):
                return respond('403 Forbidden',{'error':'Invalid CSRF token'})
            if (environ.get('wsgi.url_scheme')!='https' or
                    environ.get('HTTP_ORIGIN')!='https://'+environ.get('HTTP_HOST','')):
                return respond('403 Forbidden',{'error':'Use the same HTTPS origin'})
            try:
                length=int(environ.get('CONTENT_LENGTH') or 0)
                if environ.get('CONTENT_TYPE','').split(';')[0]!='application/json' or not 0<length<=16384:raise ValueError()
                data=json.loads(environ['wsgi.input'].read(length))
                if not isinstance(data,dict):raise ValueError()
            except (ValueError,UnicodeError):return respond('400 Bad Request',{'error':'Invalid JSON request'})
        try:
            if method=='GET' and path in self.GET:return respond('200 OK',self.client.request(self.GET[path],{}))
            if method=='POST' and path in self.POST:return respond('202 Accepted' if path.endswith(('/recover','/validate','/execute','/restore-review')) else '200 OK',self.client.request(self.POST[path],data))
            if path=='/api/capabilities' and method=='GET':
                info=self.client.request('info',{})
                return respond('200 OK',{'backup_create':bool(info['authenticated'] and info['location'] and not info['recovery_required'] and not info.get('restore_review') and not info.get('restore_preparation')),
                    'backup_overwrite':False,'restore_execute':bool(info['authenticated'] and info['location'] and not info['recovery_required'] and not info.get('restore_review')),'snapshot_management':False,'archive_delete':False,'archive_validation':bool(info['authenticated'] and info['location'] and not info['recovery_required'] and not info.get('restore_review'))})
            if path=='/api/backup/start' and method=='POST':
                return respond('202 Accepted',self.client.request('backup',{'request':data,'timezone':self.web.settings.read()['timezone']}))
            if path=='/api/execution/status' and method=='GET':
                query=parse_qs(environ.get('QUERY_STRING',''),keep_blank_values=True,strict_parsing=True,max_num_fields=2)
                if set(query)!={'request_id'} or len(query['request_id'])!=1:raise ValueError('Choose one request identity')
                job=self.client.request('status',{'request_id':query['request_id'][0]})
                return respond('200 OK',{'found':job is not None,'execution':job})
            if path=='/api/history' and method=='GET':
                rows=self.client.request('history',{})+self.web.history.list()
                return respond('200 OK',sorted(rows,key=lambda row:(row['created'],row['id']),reverse=True))
            if path=='/api/history/detail' and method=='POST':
                row=self.detail(data.get('id'))
                return respond('200 OK',row) if row else respond('404 Not Found',{'error':'History record is unavailable'})
            if path in ('/api/history/clear','/api/history/download') and method=='POST':
                ids=data.get('ids')
                if (not isinstance(ids,list) or not 1<=len(ids)<=1000 or len(set(ids))!=len(ids)
                        or any(type(i)is not int or i<=0 for i in ids)):raise ValueError('Choose distinct history records')
                if path.endswith('/clear'):
                    if data.get('confirmed') is not True:raise ValueError('Confirm history removal')
                    root=[i for i in ids if i>EVENT_BASE];panel=[i for i in ids if i<=EVENT_BASE]
                    if root:self.client.request('history_clear',{'ids':root})
                    if panel:self.web.history.clear(panel)
                    return respond('200 OK',{'cleared':ids})
                name,kind,body=history_logs(self,ids)
                start('200 OK',[('Content-Type',kind),('Content-Length',str(len(body))),('Cache-Control','no-store'),
                                ('Content-Disposition','attachment; filename="'+name+'"'),('X-Content-Type-Options','nosniff')])
                return [body]
            return respond('405 Method Not Allowed',{'error':'Method not allowed'})
        except (ValueError,KeyError,TypeError):return respond('400 Bad Request',{'error':'Invalid QNAP request'})
        except MissingHistoryEvent:return respond('404 Not Found',{'error':'History record is unavailable'})
        except Exception as error:
            # Only fixed-purpose worker errors are exposed; never request bodies.
            message=str(error) if isinstance(error,QnapRemoteError) else 'QNAP service is unavailable; check operation status before retrying'
            return respond('409 Conflict',{'error':message})

    def detail(self,identifier):
        if type(identifier)is not int or identifier<=0:raise ValueError('Choose a history record')
        return self.client.request('history_detail',{'id':identifier}) if identifier>EVENT_BASE else self.web.history.detail(identifier)


class QnapRemoteError(RuntimeError):
    pass
