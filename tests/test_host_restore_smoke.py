import subprocess
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from tests.host_restore_smoke import check_fixture_databases, wait_for_manual_stop
from tests.host_snapshot_smoke import SandboxAPI, archive_fixture


class HostRestoreTests(unittest.TestCase):
    def test_manual_wait_observes_status_without_start_stop(self):
        api = Mock()
        api.call.side_effect = [[{'name':'plex','state':state}]
                                for state in ('RUNNING', 'STOPPING', 'STOPPED')]
        wait_for_manual_stop(api, clock=lambda:0, pause=Mock())
        self.assertTrue(all(call.args == ('app.query', [['name','=','plex']])
                            for call in api.call.call_args_list))

    def test_unknown_or_expired_status_never_proceeds(self):
        for state, clock, error in (
            ('UNKNOWN', lambda:0, RuntimeError),
            ('RUNNING', Mock(side_effect=[0, 601]), TimeoutError),
        ):
            api = Mock()
            api.call.return_value = [{'name':'plex','state':state}]
            with self.subTest(state=state), self.assertRaises(error):
                wait_for_manual_stop(api, clock=clock, pause=Mock())

    def test_fixture_database_check_is_read_only_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_fixture(root)
            check_fixture_databases(root)
            directory = root/'Library/Application Support/Plex Media Server/Plug-in Support/Databases'
            database = directory/'com.plexapp.plugins.library.db'
            database.write_bytes(b'not a database')
            with self.assertRaises(sqlite3.DatabaseError):
                check_fixture_databases(root)

    def test_restore_adapter_requires_exact_owned_restore_snapshot_and_no_force(self):
        dataset = 'TrueNAS/pcc-test-'+'a'*32
        identifier = dataset+'@pcc-restore-'+'b'*32
        runner = Mock(return_value=subprocess.CompletedProcess([],0,'True\n',''))
        api = SandboxAPI(dataset, runner, allow_restore=True)
        options = {'recursive':False, 'recursive_clones':False,
                   'force':False, 'recursive_rollback':False}
        with self.assertRaises(ValueError):
            api.call('pool.snapshot.rollback', identifier, options)
        api.call('pool.snapshot.create', {'dataset':dataset,
            'name':identifier.split('@')[1], 'recursive':False})
        api.call('pool.snapshot.rollback', identifier, options)
        self.assertEqual(runner.call_count,2)
        with self.assertRaises(ValueError):
            api.call('pool.snapshot.rollback', identifier, {**options,'force':True})
        with self.assertRaises(ValueError):
            api.call('pool.snapshot.rollback', 'TrueNAS/ix-apps/app_mounts/plex/config@other', options)
        self.assertEqual(runner.call_count,2)
