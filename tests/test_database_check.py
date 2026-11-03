import sqlite3
import tempfile
import unittest
import subprocess
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from plexconfigcontrol.database_check import check_databases, DATABASES, DatabaseCheckError
from plexconfigcontrol.database_check import probe_sqlite, PlexDatabaseChecker

class DatabaseTests(unittest.TestCase):
    def test_probe_uses_only_memory_and_requires_expected_version(self):
        calls=[]
        def runner(args,**kwargs):
            calls.append((args,kwargs))
            return SimpleNamespace(returncode=0,stdout='3.53.3\nok\n')
        self.assertEqual(probe_sqlite('/opt/plex/Plex SQLite','3.53.3',runner=runner),'3.53.3')
        self.assertEqual(calls[0][0][1],':memory:')
        self.assertEqual(calls[0][1]['timeout'],15)
        with self.assertRaises(DatabaseCheckError):
            probe_sqlite('/opt/plex/Plex SQLite','3.52.0',runner=runner)
        with self.assertRaises(DatabaseCheckError):
            probe_sqlite('sqlite3','3.53.3',runner=runner)

    def test_probe_failure_never_opens_staged_databases(self):
        for failure in (FileNotFoundError('private host path'),subprocess.TimeoutExpired('sqlite',15)):
            def runner(*args,**kwargs): raise failure
            with patch('plexconfigcontrol.database_check.check_databases') as check:
                with self.assertRaises(DatabaseCheckError) as caught:
                    PlexDatabaseChecker('/opt/plex/Plex SQLite','3.53.3',runner=runner)('/staging')
                check.assert_not_called()
                self.assertNotIn('private host path',str(caught.exception))

    def test_restore_adapter_checks_staging_after_self_test(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); self.prepare(root); calls=[]
            def runner(args,**kwargs):
                calls.append(args)
                return SimpleNamespace(returncode=0,stdout='3.53.3\nok\n' if args[1]==':memory:' else 'ok\n')
            checker=PlexDatabaseChecker('/opt/plex/Plex SQLite','3.53.3',runner=runner)
            self.assertEqual(checker(root),list(DATABASES))
            self.assertEqual(calls[0][1],':memory:')
            self.assertEqual(len(calls),3)
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
