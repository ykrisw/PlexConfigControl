import tempfile
import unittest
import json
from pathlib import Path
from plexconfigcontrol.archive_store import file_identity
from plexconfigcontrol.web import Web
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.restore_readiness import restore_readiness
from plexconfigcontrol.publication_intent import record
from plexconfigcontrol.locking import operation_lock,OperationBusy
from test_plex import API

NAME='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'

class ReadinessTests(unittest.TestCase):
    def test_modified_replaced_removed_and_linked_archives_block_readiness(self):
        with tempfile.TemporaryDirectory() as d:
            store=StateStore(d); self.prepare(store)
            api=API([{'name':'plex','state':'STOPPED'}]); path=Path(d)/NAME
            self.assertTrue(restore_readiness(store,d,api,d)['ready'])
            path.write_bytes(b'changed')
            self.assertEqual(restore_readiness(store,d,api,d)['reason'],'ARCHIVE_CHANGED_REVALIDATE')
            path.unlink(); path.write_bytes(b'archive')
            self.assertFalse(restore_readiness(store,d,api,d)['ready'])
            path.unlink()
            self.assertFalse(restore_readiness(store,d,api,d)['ready'])
            target=Path(d)/'external'; target.write_bytes(b'archive'); path.symlink_to(target)
            self.assertFalse(restore_readiness(store,d,api,d)['ready'])
            self.assertFalse(restore_readiness(store,d,api,None)['ready'])

    def test_authenticated_readiness_endpoint(self):
        with tempfile.TemporaryDirectory() as d:
            app=Web(d,d,truenas_api=API([{'name':'plex','state':'STOPPED'}]))
            self.prepare(app.operation_store)
            def request(token=''):
                status=[]
                body=b''.join(app({'REQUEST_METHOD':'GET','PATH_INFO':'/api/restore/readiness',
                    'HTTP_COOKIE':'pcc_session='+token},lambda code,headers:status.append(code)))
                return status[0],json.loads(body)
            self.assertEqual(request()[0],'401 Unauthorized')
            token,_=app.sessions.create()
            status,result=request(token)
            self.assertEqual(status,'200 OK'); self.assertTrue(result['ready'])
            self.assertEqual(result['archive'],NAME)

    def prepare(self,store):
        path=store.directory/NAME
        path.write_bytes(b"archive")
        with store.transaction() as op:
            op.begin('RESTORE'); op.archive_validated('digest')
            op.validation_details={'status':'VALID','archive':NAME,'sha256':'digest',
                'file_identity':file_identity(path.stat())}

    def test_manual_stop_and_lost_connection_gate_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            store=StateStore(d); self.prepare(store)
            for state,reason in [('RUNNING','STOP_PLEX_MANUALLY'),('STOPPED',None),
                    ('STOPPING','PLEX_STOP_NOT_CONFIRMED'),('UNKNOWN','PLEX_STOP_NOT_CONFIRMED')]:
                api=API([{'name':'plex','state':state}])
                result=restore_readiness(store,d,api,d)
                self.assertEqual(result['reason'],reason)
                self.assertEqual(result['ready'],state=='STOPPED')
                self.assertTrue(result['confirmation_required'])
                self.assertEqual(result['confirmation_text'],'RESTORE')
                self.assertTrue(all(method=='app.query' for method,_ in api.calls))
            result=restore_readiness(store,d,API(TimeoutError('secret')),d)
            self.assertFalse(result['ready']); self.assertNotIn('secret',str(result))

    def test_validation_and_recovery_are_required_even_with_stopped_plex(self):
        with tempfile.TemporaryDirectory() as d:
            store=StateStore(d); api=API([{'name':'plex','state':'STOPPED'}])
            self.assertEqual(restore_readiness(store,d,api,d)['reason'],'VALIDATE_ARCHIVE_FIRST')
            self.prepare(store)
            with store.transaction() as op: op.validation_details['sha256']='different'
            self.assertFalse(restore_readiness(store,d,api,d)['ready'])
            record(d,'.pcc-'+'a'*32+'.tmp',NAME)
            self.assertEqual(restore_readiness(store,d,api,d)['reason'],'RECOVERY_REQUIRED')
            with operation_lock(d):
                with self.assertRaises(OperationBusy): restore_readiness(store,d,api,d)
