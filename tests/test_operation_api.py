import io
import json
import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.web import Web
from plexconfigcontrol.operations import Phase
from plexconfigcontrol.locking import OperationBusy

NAME='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'
class OperationAPITests(unittest.TestCase):
    def test_reports_waiting_restore_and_prevents_deleting_source(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); dest=root/'backup'; dest.mkdir(); (dest/NAME).write_bytes(b'archive')
            app=Web(root/'state',dest); token,_=app.sessions.create()
            selected=app.archives.list()
            with app.operation_store.transaction() as op:
                op.begin('RESTORE'); op.archive_validated('verified-digest')
            app.progress.start('RESTORE',now=100)
            app.progress.update('WAITING_FOR_PLEX_STOP',now=101)
            env={'REQUEST_METHOD':'GET','PATH_INFO':'/api/operation',
                 'HTTP_COOKIE':'pcc_session='+token,'wsgi.input':io.BytesIO()}
            codes=[]; data=json.loads(b''.join(app(env,lambda code,headers:codes.append(code))))
            self.assertEqual(codes,['200 OK'])
            self.assertEqual(data['operation']['phase'],'WAITING_FOR_PLEX_STOP')
            self.assertIsNone(data['progress']['stage_percent'])
            with self.assertRaises(OperationBusy): app.archives.delete(selected,True)
            self.assertTrue((dest/NAME).exists())
    def test_cleanup_required_prevents_archive_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); dest=root/'backup'; dest.mkdir(); (dest/NAME).write_bytes(b'archive')
            app=Web(root/'state',dest)
            with app.operation_store.transaction() as op: op.phase=Phase.RECOVERY_REQUIRED
            with self.assertRaises(OperationBusy): app.archives.delete(app.archives.list(),True)
