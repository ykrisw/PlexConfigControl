import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from plexconfigcontrol.config_writer import ConfigWriter,ConfigWriteError

class Status:
    state='STOPPED'
    def read(self): return {'state':self.state}

class WriterTests(unittest.TestCase):
    def test_checks_status_and_uses_scoped_rsync_without_mountpoint_swap(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); target=root/'target'; target.mkdir(); source=root/'source'; source.mkdir()
            info=target.stat(); calls=[]; status=Status()
            def runner(args,**kwargs): calls.append(args); return SimpleNamespace(returncode=0,stdout=b'')
            writer=ConfigWriter(target,info.st_dev,info.st_ino,status,runner=runner)
            writer.write(source); self.assertTrue(writer.verify(source))
            self.assertIn('--delete-delay',calls[0]); self.assertIn('--dry-run',calls[1])
            self.assertEqual(calls[0][-1],str(target)+'/')
            self.assertEqual(target.stat().st_ino,info.st_ino)
            status.state='RUNNING'
            with self.assertRaises(ConfigWriteError): writer.write(source)
            self.assertEqual(len(calls),2)
    def test_target_identity_change_and_verification_difference_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); target=root/'target'; target.mkdir(); source=root/'source'; source.mkdir(); info=target.stat()
            writer=ConfigWriter(target,info.st_dev,info.st_ino,Status(),runner=lambda *a,**k:SimpleNamespace(returncode=0,stdout=b'>f changed'))
            with self.assertRaises(ConfigWriteError): writer.verify(source)
            target.rename(root/'old'); target.mkdir()
            with self.assertRaises(ConfigWriteError): writer.write(source)
