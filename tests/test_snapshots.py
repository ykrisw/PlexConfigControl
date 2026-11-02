import tempfile
import unittest
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.snapshots import Snapshots, SnapshotError

class API:
    def __init__(self): self.present=set(); self.calls=[]; self.fail_create=False; self.keep=False
    def call(self, method, *args):
        self.calls.append((method,args))
        if method=='pool.snapshot.create':
            self.present.add(args[0]['dataset']+'@'+args[0]['name'])
            if self.fail_create: raise TimeoutError('reply lost')
        if method=='pool.snapshot.query': return [{'id':args[0][0][2]}] if args[0][0][2] in self.present else []
        if method=='pool.snapshot.delete' and not self.keep: self.present.remove(args[0])
        if method=='app.query': return [{'state':'RUNNING'}]

class SnapshotTests(unittest.TestCase):
    def prepare(self, directory, kind='BACKUP'):
        store=StateStore(directory)
        with store.transaction() as op:
            op.begin(kind)
            if kind=='BACKUP': op.begin_backup()
            else:
                op.archive_validated('hash'); op.observe_plex('STOPPED'); op.confirm_restore('RESTORE','STOPPED','hash')
        api=API(); return store,api,Snapshots(api,store,'test/config')
    def test_lost_reply_retains_identity(self):
        with tempfile.TemporaryDirectory() as d:
            store,api,snap=self.prepare(d); api.fail_create=True
            with self.assertRaises(TimeoutError): snap.create()
            with store.transaction() as op: self.assertIn(op.snapshot_id,api.present)
    def test_delete_requires_confirmed_absence(self):
        with tempfile.TemporaryDirectory() as d:
            store,api,snap=self.prepare(d); identifier=snap.create(); api.keep=True
            with self.assertRaises(SnapshotError): snap.remove()
            with store.transaction() as op: self.assertEqual(op.snapshot_id,identifier)
            api.keep=False; snap.remove()
            with store.transaction() as op: self.assertIsNone(op.snapshot_id)
    def test_rollback_rejects_running_plex(self):
        with tempfile.TemporaryDirectory() as d:
            store,api,snap=self.prepare(d,'RESTORE'); snap.create()
            with self.assertRaises(SnapshotError): snap.rollback()
            self.assertFalse(any(m=='pool.snapshot.rollback' for m,_ in api.calls))
