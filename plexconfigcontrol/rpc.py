"""TrueNAS JSON-RPC over an authenticated TLS WebSocket connection.

Connection factory must supply send/recv/close and enforce TLS verification and
receive timeouts. Mutating requests are never automatically retried.
"""
import json
import threading
from urllib.parse import urlsplit

class RPCError(RuntimeError):
    pass

class TrueNASClient:
    ALLOWED={'app.query','pool.snapshot.query','pool.snapshot.create',
             'pool.snapshot.delete','pool.snapshot.rollback'}
    def __init__(self,url,username,api_key,connection_factory):
        parsed=urlsplit(url)
        if parsed.scheme!='wss' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Verified WSS endpoint required')
        if parsed.query or parsed.fragment:
            raise ValueError('Endpoint must not contain credentials or query parameters')
        self.url=url; self.username=username; self._key=api_key
        self.factory=connection_factory; self.connection=None; self.serial=0
        self.lock=threading.Lock()

    def _request(self,method,params):
        self.serial+=1; request_id=self.serial
        self.connection.send(json.dumps({'jsonrpc':'2.0','id':request_id,'method':method,'params':params}))
        for _ in range(100):
            raw=self.connection.recv()
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
        with self.lock:
            try:
                if self.connection is None:
                    self.connection=self.factory(self.url)
                    result=self._request('auth.login_ex',[{
                        'mechanism':'API_KEY_PLAIN','username':self.username,
                        'api_key':self._key,'login_options':{'user_info':False}}])
                    if not isinstance(result,dict) or result.get('response_type')!='SUCCESS':
                        raise RPCError('TrueNAS authentication failed')
                return self._request(method,list(params))
            except Exception:
                if self.connection is not None:
                    try: self.connection.close()
                    except Exception: pass
                self.connection=None
                # Do not leak server errors, secrets or transport diagnostics.
                raise RPCError('TrueNAS request failed; result may require reconciliation') from None
