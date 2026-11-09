import io
import json
import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.backup_plan import plan_backup
from plexconfigcontrol.locking import operation_lock, OperationBusy
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.publication_intent import record
from plexconfigcontrol.web import Web
from plexconfigcontrol.naming import Naming, save_naming

NAMES = ['TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz',
         'TrueNASPlexConfig_2026.11.03_05.15.35.tar.gz']

class BackupPlanTests(unittest.TestCase):
    def test_current_count_controls_question_after_external_deletions(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); dest=root/'Plex Config'; dest.mkdir(); state=root/'state'
            self.assertEqual(plan_backup(dest,state)['action'],'CREATE_NEW')
            (dest/NAMES[0]).write_bytes(b'first')
            (dest/'unrelated.txt').write_text('keep')
            one=plan_backup(dest,state)
            self.assertEqual(one['action'],'ASK_OVERWRITE_OR_NEW')
            self.assertEqual(one['existing_archive']['name'],NAMES[0])
            self.assertFalse(one['overwrite_available'])
            (dest/NAMES[1]).write_bytes(b'second')
            self.assertEqual(plan_backup(dest,state)['action'],'CREATE_NEW')
            (dest/NAMES[0]).unlink()
            self.assertEqual(plan_backup(dest,state)['existing_archive']['name'],NAMES[1])
            self.assertEqual((dest/'unrelated.txt').read_text(),'keep')

    def test_busy_operation_and_pending_publication_block_plans(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); dest=root/'dest'; dest.mkdir(); state=root/'state'; store=StateStore(state)
            with operation_lock(state):
                with self.assertRaises(OperationBusy): plan_backup(dest,state)
            with store.transaction() as op: op.begin('RESTORE')
            with self.assertRaises(OperationBusy): plan_backup(dest,state)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); dest=root/'dest'; dest.mkdir(); state=root/'state'; StateStore(state)
            record(state,'.pcc-'+'b'*32+'.tmp',NAMES[0])
            with self.assertRaises(OperationBusy): plan_backup(dest,state)

    def test_endpoint_requires_authentication_and_only_prepares(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); dest=root/'dest'; dest.mkdir(); app=Web(root/'state',dest)
            def request(token=''):
                status=[]
                body=b''.join(app({'REQUEST_METHOD':'GET','PATH_INFO':'/api/backup/plan',
                    'HTTP_COOKIE':'pcc_session='+token,'wsgi.input':io.BytesIO()},
                    lambda code,headers: status.append(code)))
                return status[0],json.loads(body)
            self.assertEqual(request()[0],'401 Unauthorized')
            token,_=app.sessions.create()
            code,body=request(token)
            self.assertEqual(code,'200 OK'); self.assertEqual(body['archive_count'],0)
            self.assertEqual(body['archive_prefix'],'PlexConfig')
            save_naming(root/'state',Naming(archive_prefix='DomowyPlex'))
            self.assertEqual(request(token)[1]['archive_prefix'],'DomowyPlex')
            self.assertEqual(list(dest.iterdir()),[])
