"""Outcome persistence and authenticated metadata, independent of archive listing."""
import json
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from plexconfigcontrol.operations import Operation, Phase
from plexconfigcontrol.outcome import describe_outcome
from plexconfigcontrol.publication_recovery import PublicationRecovery
from plexconfigcontrol.publish import publish_new
from plexconfigcontrol.startup import reconcile_startup
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.web import Web

NAME='TrueNASPlexConfig_2026.11.03_12.00.00.tar.gz'


class OutcomeTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        from test_backup_overwrite import ReplacementTests
        with ReplacementTests().fixture() as fixture:yield fixture

    def request(self,app,path):
        from test_runtime import RuntimeTests
        token,_=app.sessions.create()
        status,_,body=RuntimeTests().request(app,path,cookie='pcc_session='+token)
        self.assertEqual(status,'200 OK')
        return json.loads(body)

    def test_only_allowlisted_codes_and_archive_names_can_be_published(self):
        value={'code':'BACKUP_PUBLISHED_REVIEW','archive':NAME}
        self.assertEqual(describe_outcome(value),value)
        for invalid in (None,[],{'code':'secret'},dict(value,extra='private secret'),
                        {'code':'unknown','archive':NAME},{'code':'BACKUP_FAILED','archive':'/private/secret'},
                        {'code':'BACKUP_COMPLETED','archive':None}, {'code':[],'archive':NAME}):
            with self.subTest(invalid=invalid):self.assertIsNone(describe_outcome(invalid))
        self.assertEqual(describe_outcome({'code':'BACKUP_INTERRUPTED','archive':None}),
                         {'code':'BACKUP_INTERRUPTED','archive':None})

    def test_old_state_without_outcome_loads_and_new_operation_clears_previous_result(self):
        with tempfile.TemporaryDirectory() as directory:
            store=StateStore(directory)
            with store._connect() as db:
                payload=json.loads(db.execute('SELECT payload FROM operation').fetchone()[0])
                payload.pop('outcome')
                db.execute('UPDATE operation SET payload=?',(json.dumps(payload),))
            with StateStore(directory).transaction() as operation:self.assertIsNone(operation.outcome)
        operation=Operation(phase=Phase.SUCCESS,outcome={'code':'BACKUP_COMPLETED','archive':NAME})
        operation.begin('RESTORE');self.assertIsNone(operation.outcome)

    def test_success_outcome_is_durable_and_does_not_assert_current_file_existence(self):
        with self.fixture() as (backup,selected,old,api,store,history,progress):
            backup.run_new(create_another=selected)
            with StateStore(backup.state).transaction() as operation:
                self.assertEqual(operation.outcome,{'code':'BACKUP_COMPLETED','archive':NAME})
                self.assertEqual(operation.phase,Phase.SUCCESS)
            # Historical completion remains a fact after a user moves the file.
            (backup.destination/NAME).unlink()
            app=Web(backup.state,archive_directory=backup.destination)
            result=self.request(app,'/api/operation')
            self.assertEqual(result['operation']['outcome']['code'],'BACKUP_COMPLETED')
            self.assertNotIn('exists',result['operation']['outcome'])
            self.assertEqual(result['progress']['stage'],'COMPLETED')

    def test_published_reporting_failure_is_distinct_from_failure_before_publication(self):
        for published in (False,True):
            with self.subTest(published=published),self.fixture() as fixture:
                backup,selected,old,api,store,history,progress=fixture
                original=history.add
                def failed_history(kind,status,*args):
                    if status=='SUCCESS':raise OSError('reporting failed')
                    return original(kind,status,*args)
                target=(patch.object(history,'add',side_effect=failed_history) if published else
                        patch('plexconfigcontrol.backup.create_archive',side_effect=OSError('archive failed')))
                with target:
                    with self.assertRaises(OSError):backup.run_new(create_another=selected)
                app=Web(backup.state,archive_directory=backup.destination)
                result=self.request(app,'/api/operation')
                expected='BACKUP_PUBLISHED_REVIEW' if published else 'BACKUP_FAILED'
                self.assertEqual(result['operation']['outcome'],{'code':expected,'archive':NAME})
                self.assertNotEqual(result['operation']['phase'],'SUCCESS')
                recovery=self.request(app,'/api/recovery')
                self.assertEqual(recovery['outcome'],result['operation']['outcome'])
                self.assertFalse(recovery['publication_resolution_supported'])

    def test_ambiguous_publication_is_not_marked_published_or_successful(self):
        with self.fixture() as (backup,selected,old,api,store,*_):
            def ambiguous(*args):
                publish_new(*args)
                raise OSError('lost publication reply')
            with patch('plexconfigcontrol.backup.publish_new',side_effect=ambiguous):
                with self.assertRaises(OSError):backup.run_new(create_another=selected)
            with store.transaction() as operation:
                self.assertEqual(operation.outcome['code'],'BACKUP_PUBLICATION_UNCERTAIN')
                self.assertEqual(operation.phase,Phase.RECOVERY_REQUIRED)
            self.assertTrue((backup.destination/NAME).exists())

    def test_startup_interruption_preserves_known_archive_but_never_success(self):
        with self.fixture() as (backup,_,_,_,store,history,progress):
            with store.transaction() as operation:
                operation.kind='BACKUP';operation.phase=Phase.RUNNING
                operation.outcome={'code':'BACKUP_IN_PROGRESS','archive':NAME}
            reconcile_startup(store,progress,history,backup.state)
            with store.transaction() as operation:
                self.assertEqual(operation.outcome,{'code':'BACKUP_INTERRUPTED','archive':NAME})
                self.assertEqual(operation.phase,Phase.RECOVERY_REQUIRED)

    def test_reconciliation_records_reverification_without_changing_original_result_to_success(self):
        with self.fixture() as (backup,selected,old,api,store,history,progress):
            with patch('plexconfigcontrol.backup.retire_original',side_effect=OSError('retirement failed')):
                with self.assertRaises(OSError):backup.run_overwrite(selected)
            recovery=PublicationRecovery(store,history,progress,backup.state,backup.destination)
            recovery.keep_archives(recovery.inspect()['confirmation_token'],confirmed=True)
            with store.transaction() as operation:
                self.assertEqual(operation.outcome,{'code':'BACKUP_RECONCILED','archive':NAME})
                self.assertEqual(operation.phase,Phase.FAILED)

    def test_malformed_outcome_contents_do_not_reach_api_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Web(directory)
            with app.operation_store.transaction() as operation:
                operation.kind='BACKUP';operation.phase=Phase.RECOVERY_REQUIRED
                operation.outcome={'code':'private secret','archive':'/private/secret'}
            for route in ('/api/operation','/api/recovery'):
                result=self.request(app,route)
                self.assertNotIn('secret',str(result))
                self.assertIsNone(result['operation']['outcome'] if route=='/api/operation' else result['outcome'])

    def test_outcome_change_during_snapshot_read_rejects_stale_confirmation(self):
        from test_runtime import RuntimeTests
        with tempfile.TemporaryDirectory() as directory:
            app=Web(directory);token,_=app.sessions.create()
            identifier='test/config@pcc-backup-'+'a'*32
            with app.operation_store.transaction() as operation:
                operation.kind='BACKUP';operation.phase=Phase.RECOVERY_REQUIRED;operation.snapshot_id=identifier
                operation.outcome={'code':'BACKUP_FAILED','archive':NAME}
            def inspector():
                with app.operation_store.transaction() as operation:
                    operation.outcome={'code':'BACKUP_PUBLISHED_REVIEW','archive':NAME}
                return {'phase':'RECOVERY_REQUIRED','kind':'BACKUP','snapshot_id':identifier,'snapshot_state':'ABSENT'}
            app.recovery_inspector=inspector
            status,_,body=RuntimeTests().request(app,'/api/recovery',cookie='pcc_session='+token)
            self.assertEqual(status,'409 Conflict')
            self.assertNotIn('snapshot_state',json.loads(body))

    def test_reading_outcome_after_history_clear_does_not_recreate_events_or_edit_logs(self):
        with self.fixture() as (backup,selected,old,api,store,history,progress):
            backup.run_new(create_another=selected)
            logs={path.name:path.read_bytes() for path in (backup.destination/'Logs').iterdir()}
            history.clear([row['id'] for row in history.list()])
            app=Web(backup.state,archive_directory=backup.destination)
            self.assertEqual(self.request(app,'/api/operation')['operation']['outcome']['code'],'BACKUP_COMPLETED')
            self.assertEqual(history.list(),[])
            self.assertEqual(logs,{path.name:path.read_bytes() for path in (backup.destination/'Logs').iterdir()})
