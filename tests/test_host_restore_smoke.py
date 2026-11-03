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

    def test_failure_diagnostic_requires_verified_retained_state_and_rejects_unexpected_errors(self):
        from plexconfigcontrol.history import History
        from plexconfigcontrol.operations import Phase
        from plexconfigcontrol.progress import Progress
        from plexconfigcontrol.snapshots import Snapshots
        from plexconfigcontrol.state import StateStore
        from tests.host_restore_smoke import exercise_restore_failure, InjectedRestoreFailure
        dataset = 'TrueNAS/pcc-test-'+'a'*32
        identifier = dataset+'@pcc-restore-'+'b'*32
        name = 'TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base/'target'; target.mkdir()
            (target/'fixture.bin').write_bytes(b'Changed sandbox before Restore\n')
            (target/'fixture.bin').chmod(0o600)
            (target/'extra-before-restore.txt').write_bytes(b'Restore should remove this\n')
            destination = base/'Plex Config'; (destination/'Logs').mkdir(parents=True)
            (destination/'Logs/Restore_fixture.log').write_text('Rollback verified. Emergency snapshot retained.')
            store = StateStore(base/'state')
            with store.transaction() as operation:
                operation.kind = 'RESTORE'
                operation.phase = Phase.RECOVERY_REQUIRED
                operation.snapshot_id = identifier
                operation.outcome = {'code':'RESTORE_ROLLBACK_VERIFIED','archive':name}
            history = History(store.directory)
            history.add('RESTORE', 'FAILED', 'fixture log', name)
            progress = Progress(store.directory); progress.start('RESTORE'); progress.fail_closed(True)
            api = Mock(); api.owned_snapshots = {identifier}
            def call(method, *args):
                if method == 'app.query': return [{'name':'plex','state':'STOPPED'}]
                if method == 'pool.snapshot.query': return [{'id':identifier}]
                raise AssertionError('Unexpected host mutation')
            api.call.side_effect = call
            snapshots = Snapshots(api, store, dataset)
            restore = Mock(); restore.run.side_effect = InjectedRestoreFailure('test fixture')
            verify = Mock(return_value=True)
            args = (restore, name, api, store, snapshots, target, progress,
                    history, destination, verify)
            self.assertEqual(exercise_restore_failure(*args), identifier)
            with store.transaction() as operation:
                self.assertEqual(operation.snapshot_id, identifier)
            restore.run.side_effect = RuntimeError('an unexpected restore failure')
            with self.assertRaisesRegex(RuntimeError, 'unexpected'):
                exercise_restore_failure(*args)
            restore.run.side_effect = InjectedRestoreFailure('test fixture')
            verify.return_value = False
            with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
                exercise_restore_failure(*args)
