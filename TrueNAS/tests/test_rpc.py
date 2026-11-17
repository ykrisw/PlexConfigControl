import json
import unittest
from plexconfigcontrol.rpc import TrueNASClient,RPCError

class Connection:
    def __init__(self,fail=False): self.sent=[]; self.closed=False; self.fail=fail
    def send(self,text): self.sent.append(json.loads(text))
    def recv(self):
        request=self.sent[-1]
        if request['method']=='auth.login_ex': result={'response_type':'SUCCESS'}
        elif self.fail: raise TimeoutError('SECRET')
        else: result=[{'name':'plex','state':'STOPPED'}]
        return json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result})
    def close(self): self.closed=True

class RPCTests(unittest.TestCase):
    def test_authentication_and_call(self):
        c=Connection(); client=TrueNASClient('wss://nas/api/current','user','secret',lambda url:c)
        self.assertEqual(client.call('app.query', [['name','=','plex']])[0]['state'],'STOPPED')
        self.assertEqual(len(c.sent),2)
        with self.assertRaises(RPCError): client.call('app.stop','plex')
    def test_mutation_timeout_never_retried_or_leaks_secret(self):
        c=Connection(True); client=TrueNASClient('wss://nas/api/current','user','secret',lambda url:c)
        with self.assertRaises(RPCError) as error: client.call('pool.snapshot.create',{'dataset':'test'})
        self.assertNotIn('SECRET',str(error.exception)); self.assertTrue(c.closed)
        self.assertEqual(len(c.sent),2)
    def test_plaintext_transport_rejected(self):
        with self.assertRaises(ValueError): TrueNASClient('ws://nas/api/current','u','k',lambda url:None)

class Clock:
    def __init__(self): self.now=0
    def __call__(self): return self.now

class DeadlineConnection(Connection):
    def __init__(self,clock,auth_delay=0,request_delay=0,notifications=False):
        super().__init__()
        self.clock=clock; self.auth_delay=auth_delay
        self.request_delay=request_delay; self.notifications=notifications
        self.timeouts=[]
    def settimeout(self,timeout): self.timeouts.append(timeout)
    def recv(self):
        auth=self.sent[-1]['method']=='auth.login_ex'
        self.clock.now+=self.auth_delay if auth else self.request_delay
        if not auth and self.notifications:
            return json.dumps({'jsonrpc':'2.0','method':'notification'})
        return super().recv()

class RPCDeadlineTests(unittest.TestCase):
    def test_authentication_and_request_share_budget(self):
        clock=Clock(); c=DeadlineConnection(clock,auth_delay=3)
        client=TrueNASClient('wss://nas/api/current','u','k',lambda url:c,timeout=5,clock=clock)
        client.call('app.query')
        self.assertEqual(c.timeouts,[5,5,2,2])

    def test_notifications_do_not_reset_deadline(self):
        clock=Clock(); c=DeadlineConnection(clock,request_delay=2,notifications=True)
        client=TrueNASClient('wss://nas/api/current','u','k',lambda url:c,timeout=5,clock=clock)
        with self.assertRaises(RPCError): client.call('app.query')
        self.assertEqual(clock.now,6)
        self.assertTrue(c.closed)
        self.assertIsNone(client.connection)
        self.assertEqual(len(c.sent),2)

    def test_late_mutation_success_is_uncertain_and_not_retried(self):
        for method in ('pool.snapshot.create','pool.snapshot.delete','pool.snapshot.rollback'):
            with self.subTest(method=method):
                clock=Clock(); c=DeadlineConnection(clock,request_delay=6)
                client=TrueNASClient('wss://nas/api/current','u','k',lambda url:c,timeout=5,clock=clock)
                with self.assertRaises(RPCError): client.call(method,{'dataset':'test'})
                self.assertEqual([r['method'] for r in c.sent],['auth.login_ex',method])
                self.assertTrue(c.closed)

    def test_expired_authentication_does_not_send_operation(self):
        clock=Clock(); c=DeadlineConnection(clock,auth_delay=6)
        client=TrueNASClient('wss://nas/api/current','u','k',lambda url:c,timeout=5,clock=clock)
        with self.assertRaises(RPCError): client.call('pool.snapshot.create',{})
        self.assertEqual(len(c.sent),1)

    def test_busy_client_does_not_touch_owned_connection(self):
        c=Connection(); client=TrueNASClient('wss://nas/api/current','u','k',lambda url:c,timeout=.01)
        client.connection=c
        client.lock.acquire()
        try:
            with self.assertRaisesRegex(RPCError,'not sent'): client.call('app.query')
            self.assertIs(client.connection,c)
            self.assertFalse(c.closed)
            self.assertEqual(c.sent,[])
        finally:
            client.lock.release()
        self.assertEqual(client.call('app.query')[0]['state'],'STOPPED')

    def test_connection_setup_consumes_same_budget(self):
        clock=Clock(); c=DeadlineConnection(clock)
        class Factory:
            def connect_with_timeout(self,url,timeout):
                self.timeout=timeout; clock.now+=2; return c
        factory=Factory()
        client=TrueNASClient('wss://nas/api/current','u','k',factory,timeout=5,clock=clock)
        client.call('app.query')
        self.assertEqual(factory.timeout,5)
        self.assertEqual(c.timeouts,[3,3,3,3])

    def test_invalid_budget_rejected(self):
        for timeout in (0,-1,601,float('inf'),float('nan')):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                TrueNASClient('wss://nas/api/current','u','k',lambda url:None,timeout=timeout)
