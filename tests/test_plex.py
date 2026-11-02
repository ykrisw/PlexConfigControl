import unittest
from plexconfigcontrol.plex import PlexStatus

class API:
    def __init__(self,result): self.result=result; self.calls=[]
    def call(self,method,*args):
        self.calls.append((method,args))
        if isinstance(self.result,Exception): raise self.result
        return self.result

class PlexTests(unittest.TestCase):
    def test_only_confirmed_stopped_allows_restore(self):
        for state in ('RUNNING','STOPPED','DEPLOYING','STOPPING','CRASHED','unexpected'):
            api=API([{'name':'plex','state':state}]); result=PlexStatus(api).read()
            self.assertEqual(result['restore_allowed'],state=='STOPPED')
            self.assertEqual(api.calls,[('app.query',([['name','=','plex']],))])
    def test_errors_missing_or_wrong_app_fail_closed(self):
        for result in (TimeoutError('secret token'),[],[{'name':'other','state':'STOPPED'}],None):
            status=PlexStatus(API(result)).read()
            self.assertEqual(status['state'],'UNKNOWN')
            self.assertFalse(status['restore_allowed'])
            self.assertNotIn('secret',str(status))
