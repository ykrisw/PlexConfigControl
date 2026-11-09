"""TrueNAS JSON-RPC over an authenticated TLS WebSocket connection.

Connection factory must supply send/recv/close and enforce TLS verification and
bounded I/O. The production transport supplies connect_with_timeout and socket
settimeout so lock wait, connection, authentication and notifications share one
request budget. Injected factories must enforce their own connection/I/O bounds.
Mutating requests are never automatically retried.
"""
import json
import threading
import time
from urllib.parse import urlsplit

class RPCError(RuntimeError):
    pass

class TrueNASClient:
    ALLOWED={'app.query','filesystem.statfs','pool.snapshot.query','pool.snapshot.create',
             'pool.snapshot.delete','pool.snapshot.rollback'}
    def __init__(self,url,username,api_key,connection_factory,timeout=30,*,clock=time.monotonic):
        if not 0<timeout<=600: raise ValueError('Invalid request timeout')
        parsed=urlsplit(url)
        if parsed.scheme!='wss' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Verified WSS endpoint required')
        if parsed.query or parsed.fragment:
            raise ValueError('Endpoint must not contain credentials or query parameters')
        self.url=url; self.username=username; self._key=api_key
        self.factory=connection_factory; self.connection=None; self.serial=0
        self.lock=threading.Lock()
        self.timeout=timeout; self.clock=clock

    def _remaining(self,deadline):
        remaining=deadline-self.clock()
        if remaining<=0: raise TimeoutError('Request deadline exceeded')
        return remaining

    def _prepare_io(self,deadline):
        remaining=self._remaining(deadline)
        setter=getattr(self.connection,'settimeout',None)
        if setter is not None: setter(remaining)

    def _request(self,method,params,deadline):
        self.serial+=1; request_id=self.serial
        self._prepare_io(deadline)
        self.connection.send(json.dumps({'jsonrpc':'2.0','id':request_id,'method':method,'params':params}))
        for _ in range(100):
            self._prepare_io(deadline)
            raw=self.connection.recv()
            self._remaining(deadline)
            if not raw or len(raw)>8*1024*1024: raise RPCError('Invalid API response')
            message=json.loads(raw)
            if not isinstance(message,dict) or message.get('jsonrpc')!='2.0':
                raise RPCError('Invalid API response')
            if 'id' not in message: continue  # asynchronous notification
            if message['id']!=request_id: raise RPCError('Unexpected response identity')
            if 'error' in message: raise RPCError('TrueNAS rejected API request')
            if 'result' not in message: raise RPCError('Missing API result')
            return message['result']
        raise RPCError('API notification limit exceeded')

    def call(self,method,*params):
        if method not in self.ALLOWED: raise RPCError('API method is not allowed')
        deadline=self.clock()+self.timeout
        if not self.lock.acquire(timeout=max(0,deadline-self.clock())):
            # Another call owns this connection. Do not close or reset it.
            raise RPCError('TrueNAS client is busy; request was not sent')
        try:
            try:
                self._remaining(deadline)
                if self.connection is None:
                    connect=getattr(self.factory,'connect_with_timeout',None)
                    self.connection=(connect(self.url,self._remaining(deadline))
                                     if connect is not None else self.factory(self.url))
                    self._remaining(deadline)
                    result=self._request('auth.login_ex',[{
                        'mechanism':'API_KEY_PLAIN','username':self.username,
                        'api_key':self._key,'login_options':{'user_info':False}}],deadline)
                    if not isinstance(result,dict) or result.get('response_type')!='SUCCESS':
                        raise RPCError('TrueNAS authentication failed')
                return self._request(method,list(params),deadline)
            except Exception:
                if self.connection is not None:
                    try: self.connection.close()
                    except Exception: pass
                self.connection=None
                # Do not leak server errors, secrets or transport diagnostics.
                raise RPCError('TrueNAS request failed; result may require reconciliation') from None
        finally:
            self.lock.release()
