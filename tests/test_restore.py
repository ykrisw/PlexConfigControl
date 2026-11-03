import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.archives import REQUIRED,validate_archive
from plexconfigcontrol.restore import Restore
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.history import History
from plexconfigcontrol.progress import Progress
from plexconfigcontrol.operations import Phase
from test_snapshots import API

class StoppedAPI(API):
    def call(self,method,*args):
        if method=='app.query':
            self.calls.append((method,args)); return [{'name':'plex','state':'STOPPED'}]
        return super().call(method,*args)

NAME='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'
class RestoreTests(unittest.TestCase):
    def run_case(self,fail=False):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); dest=root/'Plex Config'; (dest/'Logs').mkdir(parents=True)
            with tarfile.open(dest/NAME,'w:gz') as archive:
                for name in REQUIRED:
                    m=tarfile.TarInfo(name); m.size=4
                    m.uid=os.getuid(); m.gid=os.getgid()
                    archive.addfile(m,io.BytesIO(b'test'))
            store=StateStore(root/'state'); api=StoppedAPI(); history=History(root/'state')
            with store.transaction() as op:
                op.begin('RESTORE'); op.archive_validated(validate_archive(dest/NAME).sha256)
            writes=[]
            runner=Restore(api,store,history,Progress(root/'state'),root/'state',dest,'test/config',
                           lambda path:None,lambda path:writes.append(path),lambda path:not fail,lambda identifier:True)
            if fail:
                with self.assertRaises(RuntimeError): runner.run(NAME,'RESTORE')
            else: runner.run(NAME,'RESTORE')
            self.assertEqual(len(writes),1)
            with store.transaction() as op:
                self.assertEqual(op.phase,Phase.RECOVERY_REQUIRED if fail else Phase.SUCCESS)
                self.assertEqual(bool(op.snapshot_id),fail)
            self.assertEqual(bool(api.present),fail)
            self.assertEqual(any(m=='pool.snapshot.rollback' for m,_ in api.calls),fail)
            self.assertFalse(any(m in ('app.start','app.stop') for m,_ in api.calls))
    def test_success_removes_snapshot(self): self.run_case()
    def test_failure_rolls_back_and_retains_snapshot(self): self.run_case(True)
