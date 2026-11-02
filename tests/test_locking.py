import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.locking import operation_lock, OperationBusy

class LockTests(unittest.TestCase):
    def test_second_process_rejected_then_released(self):
        with tempfile.TemporaryDirectory() as directory:
            script='''import sys
from plexconfigcontrol.locking import operation_lock, OperationBusy
try:
    with operation_lock(sys.argv[1]): pass
except OperationBusy:
    sys.exit(17)
'''
            with operation_lock(directory):
                result=subprocess.run([sys.executable,'-c',script,directory])
                self.assertEqual(result.returncode,17)
            result=subprocess.run([sys.executable,'-c',script,directory])
            self.assertEqual(result.returncode,0)

    def test_exception_releases_without_unlinking(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                with operation_lock(directory):
                    inode=(Path(directory)/'operation.lock').stat().st_ino
                    raise ValueError('failure')
            with operation_lock(directory):
                self.assertEqual((Path(directory)/'operation.lock').stat().st_ino,inode)
