import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plexconfigcontrol.web import Web
from plexconfigcontrol.recovery import Recovery
from plexconfigcontrol.operations import Phase
from plexconfigcontrol.snapshots import Snapshots
from plexconfigcontrol.locking import operation_lock
from test_snapshots import API


class RecoveryEndpointTests(unittest.TestCase):
    def request(self, app, token='', *, method='GET', csrf=''):
        responses=[];raw=b'{}' if method=='POST' else b''
        result=b''.join(app({'REQUEST_METHOD':method,'PATH_INFO':'/api/recovery',
            'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),
            'HTTP_COOKIE':'pcc_session='+token,'HTTP_X_CSRF_TOKEN':csrf,
            'wsgi.input':io.BytesIO(raw)},lambda code,headers:responses.append(code)))
        return responses[0],json.loads(result)

    def prepare(self, directory):
        app=Web(directory);api=API()
        with app.operation_store.transaction() as operation:
            operation.begin('BACKUP');operation.begin_backup()
        identifier=Snapshots(api,app.operation_store,'test/config').create()
        with app.operation_store.transaction() as operation: operation.finish(False)
        return app,api,identifier

    def test_authentication_and_unknown_status_without_host_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            app,api,identifier=self.prepare(directory)
            self.assertEqual(self.request(app)[0],'401 Unauthorized')
            token,_=app.sessions.create();api.calls.clear()
            status,result=self.request(app,token)
            self.assertEqual(status,'200 OK')
            self.assertEqual(result['snapshot_id'],identifier)
            self.assertEqual(result['snapshot_state'],'UNKNOWN')
            self.assertFalse(result['removal_available'])
            self.assertFalse(result['removal_supported'])
            self.assertEqual(api.calls,[])

    def test_verified_inspection_remains_read_only_and_cannot_enable_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            app,api,identifier=self.prepare(directory)
            recovery=Recovery(api,app.operation_store,app.history,directory,'test/config')
            app.recovery_inspector=recovery.inspect
            token,csrf=app.sessions.create();api.calls.clear()
            status,result=self.request(app,token)
            self.assertEqual(status,'200 OK')
            self.assertEqual(result['snapshot_state'],'PRESENT')
            self.assertFalse(result['removal_available'])
            self.assertFalse(result['removal_supported'])
            self.assertEqual(len(api.calls),1)
            self.assertEqual(api.calls[0][0],'pool.snapshot.query')
            self.assertEqual(self.request(app,token,method='POST',csrf=csrf)[0],'404 Not Found')
            self.assertIn(identifier,api.present)
            self.assertFalse(any(method=='pool.snapshot.delete' for method,args in api.calls))
            api.present.clear()
            self.assertEqual(self.request(app,token)[1]['snapshot_state'],'ABSENT')
            with app.operation_store.transaction() as operation:
                self.assertEqual(operation.snapshot_id,identifier)
                self.assertEqual(operation.phase,Phase.RECOVERY_REQUIRED)

    def test_mismatched_inspector_reply_and_transport_errors_never_claim_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            app,api,identifier=self.prepare(directory);token,_=app.sessions.create()
            app.recovery_inspector=lambda:{'phase':'RECOVERY_REQUIRED','kind':'BACKUP',
                'snapshot_id':'another/dataset@snapshot','snapshot_state':'ABSENT','removal_supported':True}
            self.assertEqual(self.request(app,token)[1]['snapshot_state'],'UNKNOWN')
            def fail(): raise TimeoutError('secret API credentials')
            app.recovery_inspector=fail
            status,result=self.request(app,token)
            self.assertEqual(status,'503 Service Unavailable')
            self.assertNotIn('secret',str(result))
            self.assertIn(identifier,api.present)

    def test_busy_inspection_and_no_snapshot_recovery_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            app,api,identifier=self.prepare(directory);token,_=app.sessions.create()
            app.recovery_inspector=Recovery(api,app.operation_store,app.history,directory,'test/config').inspect
            with operation_lock(directory):
                self.assertEqual(self.request(app,token)[0],'409 Conflict')
            with app.operation_store.transaction() as operation: operation.snapshot_id=None
            api.calls.clear()
            result=self.request(app,token)[1]
            self.assertEqual(result['snapshot_state'],'NONE')
            self.assertEqual(api.calls,[])
            self.assertEqual(result['phase'],'RECOVERY_REQUIRED')
