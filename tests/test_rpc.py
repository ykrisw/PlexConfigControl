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
