import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from plexconfigcontrol.database_check import check_databases, DATABASES, DatabaseCheckError

class DatabaseTests(unittest.TestCase):
    def prepare(self,root):
        directory=root/'Library/Application Support/Plex Media Server/Plug-in Support/Databases'
        directory.mkdir(parents=True)
        for name in DATABASES:
            with sqlite3.connect(directory/name) as db:
                db.execute('CREATE TABLE example(id INTEGER PRIMARY KEY, value TEXT)')
        return directory
    def test_checks_both_databases_and_accepts_only_ok(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); self.prepare(root); calls=[]
            def runner(args,**kwargs):
                calls.append(args)
                with sqlite3.connect(args[1]) as db:
                    result=db.execute('PRAGMA integrity_check').fetchone()[0]
                return SimpleNamespace(returncode=0,stdout=result+'\n')
            self.assertEqual(check_databases(root,'plex-sqlite',runner=runner),list(DATABASES))
            self.assertEqual(len(calls),2)
            with self.assertRaises(DatabaseCheckError):
                check_databases(root,'plex-sqlite',runner=lambda *a,**k:SimpleNamespace(returncode=0,stdout='corrupt'))
    def test_symlink_rejected_before_executing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); directory=self.prepare(root)
            (directory/DATABASES[0]).unlink(); (directory/DATABASES[0]).symlink_to(directory/DATABASES[1])
            def forbidden(*args,**kwargs): raise AssertionError('Must not run')
            with self.assertRaises(DatabaseCheckError): check_databases(root,'plex-sqlite',runner=forbidden)
