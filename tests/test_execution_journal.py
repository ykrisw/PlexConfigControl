import io
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from plexconfigcontrol.archive_store import Archive
from plexconfigcontrol.execution import BackupRequest, RestoreRequest, ExecutionGateway, InvalidExecutionRequest
from plexconfigcontrol.execution_journal import ExecutionJournal, OperationClaim
from plexconfigcontrol.history import History
from plexconfigcontrol.locking import OperationBusy, operation_lock
from plexconfigcontrol.operations import OperationDenied, Phase
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.web import Web

NAME = 'TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'


class ExecutionJournalTests(unittest.TestCase):
    def test_lost_receipt_restart_and_concurrent_duplicates_reserve_once(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = ExecutionJournal(directory)
            request = BackupRequest('a'*32, 'NEW')
            with ThreadPoolExecutor(max_workers=4) as pool:
                rows = list(pool.map(lambda _: ExecutionJournal(directory).reserve(request), range(8)))
            self.assertEqual(sum(row.created for row in rows), 1)
            self.assertEqual({row.receipt for row in rows}, {journal.lookup(request)})
            claim = journal.claim(request)
            with self.assertRaises(OperationDenied): ExecutionJournal(directory).claim(request)
            journal.finish(claim, 'SUCCEEDED')
            replay = ExecutionJournal(directory).reserve(request)
            self.assertFalse(replay.created); self.assertEqual(replay.state, 'SUCCEEDED')
            with self.assertRaises(OperationDenied): journal.claim(request)

    def test_different_requests_compete_for_one_active_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = ExecutionJournal(directory)
            first = BackupRequest('a'*32, 'NEW'); other = BackupRequest('b'*32, 'NEW')
            journal.reserve(first)
            with self.assertRaises(OperationBusy): journal.reserve(other)
            claim = journal.claim(first); journal.finish(claim, 'FAILED')
            self.assertTrue(journal.reserve(other).created)

    def test_reused_identity_with_changed_archive_mode_digest_or_kind_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = ExecutionJournal(directory)
            archive = Archive(NAME, 1, 2, 3, 4)
            original = BackupRequest('a'*32, 'ANOTHER', archive)
            journal.reserve(original)
            for changed in (BackupRequest('a'*32, 'OVERWRITE', archive),
                            BackupRequest('a'*32, 'ANOTHER', Archive(NAME,1,2,3,5)),
                            RestoreRequest('a'*32, NAME, 'b'*64, 'RESTORE')):
                with self.subTest(request=changed):
                    with self.assertRaises(OperationDenied): journal.lookup(changed)
                    with self.assertRaises(OperationDenied): journal.reserve(changed)
            self.assertIsNotNone(journal.lookup(original))
        with tempfile.TemporaryDirectory() as directory:
            journal=ExecutionJournal(directory)
            original=RestoreRequest('c'*32, NAME, 'b'*64, 'RESTORE')
            journal.reserve(original)
            with self.assertRaises(OperationDenied):
                journal.reserve(RestoreRequest('c'*32,NAME,'d'*64,'RESTORE'))

    def test_restart_blocks_work_and_invalidates_old_claim_without_replaying(self):
        for claimed in (False,True):
            with self.subTest(claimed=claimed), tempfile.TemporaryDirectory() as directory:
                journal = ExecutionJournal(directory); request = BackupRequest('a'*32,'NEW')
                journal.reserve(request)
                claim = journal.claim(request) if claimed else None
                restarted = ExecutionJournal(directory)
                self.assertEqual(restarted.reconcile_startup(),['a'*32])
                self.assertEqual(restarted.reconcile_startup(),[])
                self.assertEqual(restarted.reserve(request).state,'RECOVERY_REQUIRED')
                with self.assertRaises(OperationBusy): restarted.reserve(BackupRequest('b'*32,'NEW'))
                with self.assertRaises(OperationDenied): restarted.claim(request)
                if claim:
                    with self.assertRaises(OperationDenied): restarted.finish(claim,'SUCCEEDED')

    def test_ownership_cannot_be_forged_or_completed_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=ExecutionJournal(directory); request=BackupRequest('a'*32,'NEW')
            journal.reserve(request); claim=journal.claim(request)
            forged=OperationClaim(claim.receipt,'0'*64)
            with self.assertRaises(OperationDenied): journal.finish(forged,'SUCCEEDED')
            journal.finish(claim,'FAILED')
            with self.assertRaises(OperationDenied): journal.finish(claim,'SUCCEEDED')

    def test_live_operation_lock_prevents_startup_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=ExecutionJournal(directory);request=BackupRequest('a'*32,'NEW');journal.reserve(request)
            with operation_lock(directory):
                with self.assertRaises(OperationBusy): journal.reconcile_startup()
            self.assertEqual(journal.reserve(request).state,'QUEUED')

    def test_history_clear_does_not_remove_deduplication_and_payload_is_not_stored(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=ExecutionJournal(directory)
            request=RestoreRequest('a'*32,NAME,'b'*64,'RESTORE');journal.reserve(request)
            history=History(directory); event=history.add('RESTORE','FAILED','private history',NAME)
            history.clear([event])
            self.assertEqual(history.list(),[])
            self.assertIsNotNone(ExecutionJournal(directory).lookup(request))
            raw=journal.path.read_bytes()
            self.assertNotIn(NAME.encode(),raw)
            self.assertNotIn(b'private history',raw)
            self.assertEqual(journal.path.stat().st_mode & 0o777,0o600)

    def test_recovery_requires_confirmation_and_clean_coordinator_without_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=ExecutionJournal(directory);request=BackupRequest('a'*32,'NEW')
            journal.reserve(request);journal.reconcile_startup()
            with self.assertRaises(OperationDenied): journal.resolve_interrupted(request.request_id)
            store=StateStore(directory)
            with store.transaction() as operation:
                operation.phase=Phase.RECOVERY_REQUIRED;operation.snapshot_id='test/config@point'
            with self.assertRaises(OperationDenied): journal.resolve_interrupted(request.request_id,confirmed=True)
            with store.transaction() as operation:
                operation.phase=Phase.FAILED;operation.snapshot_id=None
            workspace=Path(directory)/'backup-pending';workspace.mkdir()
            with self.assertRaises(OperationDenied): journal.resolve_interrupted(request.request_id,confirmed=True)
            workspace.rmdir()
            journal.resolve_interrupted(request.request_id,confirmed=True)
            self.assertEqual(journal.reserve(request).state,'FAILED')
            self.assertTrue(journal.reserve(BackupRequest('b'*32,'NEW')).created)

    def test_invalid_requests_never_reserve(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=ExecutionJournal(directory)
            for request in ({'command':'arbitrary'}, BackupRequest('a'*32,'SHELL'),
                            BackupRequest('a'*32,'NEW',Archive(NAME,1,2,3,4)),
                            RestoreRequest('a'*32,'../../config','b'*64,'RESTORE')):
                with self.subTest(request=request), self.assertRaises(InvalidExecutionRequest): journal.reserve(request)
            self.assertTrue(journal.reserve(BackupRequest('b'*32,'NEW')).created)

    def test_http_replay_returns_original_receipt_after_state_changes_without_resubmitting(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);state=root/'state';destination=root/'Plex Config'
            (destination/'Logs').mkdir(parents=True)
            journal=ExecutionJournal(state)
            backend=Mock();backend.submit.side_effect=lambda request: journal.reserve(request).receipt
            api=Mock();api.call.return_value=[{'name':'plex','state':'RUNNING'}]
            gateway=ExecutionGateway(state,destination,api,backend,receipt_lookup=journal.lookup)
            web=Web(state,destination,api,execution_service=gateway);token,csrf=web.sessions.create()
            def post(data):
                encoded=json.dumps(data).encode();responses=[]
                env={'REQUEST_METHOD':'POST','PATH_INFO':'/api/backup/start',
                    'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(encoded)),
                    'wsgi.input':io.BytesIO(encoded),'HTTP_COOKIE':'pcc_session='+token,'HTTP_X_CSRF_TOKEN':csrf}
                body=b''.join(web(env,lambda status,headers:responses.append(status)))
                return responses[0],json.loads(body)
            data={'request_id':'a'*32,'mode':'NEW','confirmed':True}
            first=post(data);self.assertEqual(first[0],'202 Accepted')
            with web.operation_store.transaction() as operation: operation.begin('BACKUP');operation.begin_backup()
            api.call.return_value=[{'name':'plex','state':'STOPPED'}]
            (destination/NAME).write_bytes(b'an archive now exists')
            self.assertEqual(post(data),first)
            backend.submit.assert_called_once()
            changed={**data,'mode':'ANOTHER','archive':{
                'name':NAME,'size':'25','device':'1','inode':'1','modified_ns':'1'}}
            self.assertEqual(post(changed)[0],'409 Conflict')
            backend.submit.assert_called_once()

    def test_concurrent_claims_have_exactly_one_execution_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=ExecutionJournal(directory);request=BackupRequest('a'*32,'NEW');journal.reserve(request)
            def claim(_):
                try: return ExecutionJournal(directory).claim(request)
                except OperationDenied: return None
            with ThreadPoolExecutor(max_workers=4) as pool:
                owners=[owner for owner in pool.map(claim,range(8)) if owner is not None]
            self.assertEqual(len(owners),1)
            self.assertNotIn(owners[0].token.encode(),journal.path.read_bytes())
            journal.finish(owners[0],'FAILED')

    def test_restore_replay_survives_lost_readiness_but_changed_digest_never_reuses_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);state=root/'state';destination=root/'Plex Config';destination.mkdir()
            journal=ExecutionJournal(state)
            request=RestoreRequest('a'*32,NAME,'b'*64,'RESTORE');journal.reserve(request)
            backend=Mock();api=Mock()
            gateway=ExecutionGateway(state,destination,api,backend,receipt_lookup=journal.lookup)
            result=gateway.restore({'request_id':request.request_id,'archive':NAME,
                                    'sha256':request.sha256,'confirmation':'RESTORE'})
            self.assertTrue(result['accepted'])
            backend.submit.assert_not_called();api.call.assert_not_called()
            with self.assertRaises(OperationDenied):
                gateway.restore({'request_id':request.request_id,'archive':NAME,
                                 'sha256':'c'*64,'confirmation':'RESTORE'})
            backend.submit.assert_not_called();api.call.assert_not_called()
