"""Installer guards and process identification; no actual host signals/removal."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pcc_orphan_cleanup',ROOT/'build/orphan_cleanup.py')
orphans=importlib.util.module_from_spec(spec);spec.loader.exec_module(orphans)

class Lifecycle(unittest.TestCase):
    def test_uninstall_hook_stops_before_deleting_any_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'PCC';(root/'python/bin').mkdir(parents=True)
            python=root/'python/bin/python3';python.write_text('#!/bin/sh\nexit 1\n');python.chmod(0o755)
            marker=root/'application-data';marker.write_text('preserve')
            output=Path(folder)/'uninstall.sh'
            env={**os.environ,'SYS_QPKG_DIR':str(root),'PCC_ROUTINES':str(ROOT/'build/qpkg/package_routines'),'PCC_OUTPUT':str(output)}
            subprocess.run(['bash','-c','source "$PCC_ROUTINES"; printf "%s\\n" "$PKG_PRE_REMOVE" > "$PCC_OUTPUT"'],env=env,check=True)
            text=output.read_text();self.assertNotIn('$SYS_QPKG_DIR',text)
            self.assertIn(str(root/'launcher.py'),text)
            output.write_text(text+'\nrm -f "'+str(marker)+'"\n')
            result=subprocess.run(['sh',str(output)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertTrue(marker.exists())
            python.write_text('#!/bin/sh\nexit 0\n')
            result=subprocess.run(['sh',str(output)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0);self.assertFalse(marker.exists())
    def test_pid_reuse_never_receives_signal(self):
        record=(123,'old-start',0,'/share/DATA/.qpkg/PCC','--supervise','exe')
        calls=[]
        with patch.object(orphans,'identify',return_value=(123,'new-start',0,record[3],record[4],'exe')):
            orphans.stop_identified(record,terminate=calls.append,pause=lambda n:None)
        self.assertEqual(calls,[])
    def test_graceful_stop_without_forced_kill(self):
        record=(123,'start',0,'/share/DATA/.qpkg/PCC','--supervise','exe');calls=[]
        def terminate(pid):calls.append(pid)
        with patch.object(orphans,'identify',side_effect=[record,record,None]):
            orphans.stop_identified(record,terminate=terminate,pause=lambda n:None)
        self.assertEqual(calls,[123])
    def test_nonresponsive_process_aborts_without_force(self):
        record=(123,'start',0,'/share/DATA/.qpkg/PCC','--supervise','exe');calls=[]
        with patch.object(orphans,'identify',return_value=record):
            with self.assertRaises(RuntimeError):orphans.stop_identified(record,terminate=calls.append,pause=lambda n:None,attempts=2)
        self.assertEqual(calls,[123])

if __name__=='__main__':unittest.main()
