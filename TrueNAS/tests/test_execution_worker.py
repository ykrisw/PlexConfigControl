import io
import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

from plexconfigcontrol.archive_store import ArchiveStore
from plexconfigcontrol.archives import REQUIRED
from plexconfigcontrol.backup import Backup
from plexconfigcontrol.backup_archive import create_archive
from plexconfigcontrol.execution import BackupRequest, RestoreRequest
from plexconfigcontrol.execution_worker import ExecutionWorker, _BorrowedGuard
from plexconfigcontrol.history import History
from plexconfigcontrol.locking import OperationBusy, operation_lock
from plexconfigcontrol.operations import OperationDenied, Phase
from plexconfigcontrol.progress import Progress
from plexconfigcontrol.restore import Restore
from plexconfigcontrol.restore_validation import RestoreValidation
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.web import Web

NAME='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'


class API:
    def __init__(self): self.state='RUNNING'; self.present=set(); self.calls=[]
    def call(self, method, *args):
        self.calls.append((method,args))
        if method=='app.query': return [{'name':'plex','state':self.state}]
        if method=='pool.snapshot.create': self.present.add(args[0]['dataset']+'@'+args[0]['name'])
        elif method=='pool.snapshot.query': return [{'id':args[0][0][2]}] if args[0][0][2] in self.present else []
        elif method=='pool.snapshot.delete': self.present.remove(args[0])
        elif method=='pool.snapshot.rollback': return None
        elif method!='app.query': raise AssertionError('Unexpected API method')


class WorkerTests(unittest.TestCase):
    @contextmanager
    def fixture(self, *, blocked=False):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);state=root/'state';destination=root/'Plex Config'
            (destination/'Logs').mkdir(parents=True)
            source=root/'snapshot';source.mkdir()
            for name in REQUIRED:
                path=source/name.removeprefix('config/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
            api=API();store=StateStore(state);history=History(state);progress=Progress(state)
            entered=threading.Event();release=threading.Event()
            if not blocked: release.set()
            @contextmanager
            def reader(identifier):
                self.assertIn(identifier,api.present)
                entered.set()
                if not release.wait(3): raise RuntimeError('Test release timeout')
                yield source
            backup_factory=Mock(side_effect=lambda:Backup(api,store,history,progress,state,destination,'test/config',reader))
            write=Mock()
            restore_factory=Mock(side_effect=lambda:Restore(api,store,history,progress,state,destination,
                'test/config',lambda _:None,write,lambda _:True,lambda _:True))
            worker=ExecutionWorker(state,destination,'test/config',api,backup_factory,restore_factory)
            try: yield worker,api,store,history,progress,root,entered,release,backup_factory,restore_factory,write
            finally: release.set();worker.close()

    def test_real_backup_runs_in_background_holds_lock_and_replay_never_runs_again(self):
        with self.fixture(blocked=True) as (worker,api,store,history,progress,root,entered,release,bf,rf,write):
            request=BackupRequest('a'*32,'NEW',prefix='Plex_Living-Room')
            receipt=worker.submit(request)
            self.assertTrue(entered.wait(3))
            self.assertEqual(worker.journal.current()['state'],'RUNNING')
            with self.assertRaises(OperationBusy):
                with operation_lock(worker.state): pass
            self.assertEqual(worker.submit(request),receipt)
            with self.assertRaises(OperationDenied):
                worker.submit(BackupRequest(request.request_id,'NEW',prefix='Different'))
            with self.assertRaises(OperationBusy): worker.submit(BackupRequest('b'*32,'NEW'))
            release.set();worker.close()
            self.assertEqual(worker.journal.current()['state'],'SUCCEEDED')
            self.assertEqual(len(list(worker.destination.glob('Plex_Living-Room_*.tar.gz'))),1)
            self.assertEqual(api.present,set());self.assertEqual(history.list()[0]['status'],'SUCCESS')
            self.assertEqual(worker.submit(request),receipt);bf.assert_called_once();rf.assert_not_called()
            self.assertFalse(any(method in ('app.start','app.stop') for method,args in api.calls))
            with operation_lock(worker.state): pass

    def test_http_acceptance_and_status_are_bound_to_request_and_no_owner_token_is_exposed(self):
        with self.fixture(blocked=True) as (worker,api,store,history,progress,root,entered,release,*_):
            web=Web(worker.state,worker.destination,api,execution_service=worker.gateway())
            token,csrf=web.sessions.create()
            data=json.dumps({'request_id':'a'*32,'mode':'NEW','confirmed':True}).encode()
            responses=[]
            body=b''.join(web({'REQUEST_METHOD':'POST','PATH_INFO':'/api/backup/start',
                'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(data)),'wsgi.input':io.BytesIO(data),
                'HTTP_COOKIE':'pcc_session='+token,'HTTP_X_CSRF_TOKEN':csrf},
                lambda status,headers:responses.append(status)))
            self.assertEqual(responses,['202 Accepted']);self.assertTrue(json.loads(body)['accepted'])
            self.assertTrue(entered.wait(3))
            responses=[]
            body=b''.join(web({'REQUEST_METHOD':'GET','PATH_INFO':'/api/operation',
                'HTTP_COOKIE':'pcc_session='+token},lambda status,headers:responses.append(status)))
            result=json.loads(body)
            self.assertEqual(result['execution']['request_id'],'a'*32)
            self.assertEqual(result['execution']['state'],'RUNNING')
            self.assertEqual(set(result['execution']),{'request_id','kind','state','created_ns','updated_ns'})
            self.assertIsInstance(result['execution']['created_ns'],str)
            self.assertNotIn('owner_hash',body.decode());release.set()

    def test_backend_rechecks_plex_and_selection_even_without_gateway(self):
        with self.fixture() as (worker,api,store,history,progress,root,entered,release,bf,rf,write):
            api.state='STOPPED'
            with self.assertRaises(OperationDenied): worker.submit(BackupRequest('a'*32,'NEW'))
            self.assertIsNone(worker.journal.current());bf.assert_not_called()
            api.state='RUNNING';(worker.destination/NAME).write_bytes(b'old')
            selected=ArchiveStore(worker.destination,worker.state).list()[0]
            (worker.destination/NAME).write_bytes(b'changed outside app')
            with self.assertRaises(OperationDenied): worker.submit(BackupRequest('b'*32,'OVERWRITE',selected))
            self.assertIsNone(worker.journal.current());bf.assert_not_called()

    def prepare_restore(self, worker, api, root, store, history):
        api.state='STOPPED'
        create_archive(root/'snapshot',worker.destination/NAME)
        result=RestoreValidation(worker.destination,worker.state,store,history).validate(NAME)
        return RestoreRequest('c'*32,NAME,result['sha256'],'RESTORE')

    def test_real_restore_coordinator_finishes_with_its_snapshot_removed(self):
        with self.fixture() as (worker,api,store,history,progress,root,entered,release,bf,rf,write):
            request=self.prepare_restore(worker,api,root,store,history)
            worker.submit(request);worker.close()
            self.assertEqual(worker.journal.current()['state'],'SUCCEEDED')
            write.assert_called_once();rf.assert_called_once();bf.assert_not_called()
            self.assertEqual(api.present,set());self.assertEqual(api.state,'STOPPED')
            with store.transaction() as operation:self.assertEqual(operation.outcome['code'],'RESTORE_COMPLETED')

    def test_restore_failure_retains_recovery_block_and_never_accepts_second_job(self):
        with self.fixture() as (worker,api,store,history,progress,root,entered,release,bf,rf,write):
            request=self.prepare_restore(worker,api,root,store,history)
            write.side_effect=RuntimeError('SECRET simulated write failure')
            worker.submit(request);worker.close()
            self.assertEqual(worker.journal.current()['state'],'RECOVERY_REQUIRED')
            self.assertEqual(len(api.present),1);self.assertEqual(api.state,'STOPPED')
            with store.transaction() as operation:self.assertEqual(operation.outcome['code'],'RESTORE_ROLLBACK_VERIFIED')
            self.assertEqual(history.list()[0]['status'],'FAILED')
            self.assertNotIn('SECRET',json.dumps(worker.journal.current()))

    def test_restore_queued_digest_cannot_be_replaced_by_another_validation(self):
        with self.fixture() as (worker,api,store,history,progress,root,entered,release,bf,rf,write):
            request=self.prepare_restore(worker,api,root,store,history)
            with store.transaction() as operation:
                operation.archive_identity='b'*64;operation.validation_details['sha256']='b'*64
            with self.assertRaises(OperationDenied): worker.submit(request)
            rf.assert_not_called();write.assert_not_called();self.assertIsNone(worker.journal.current())

    def test_thread_start_failure_is_durable_failed_admission_without_host_mutation(self):
        with self.fixture() as (worker,api,store,history,progress,root,entered,release,bf,rf,write):
            thread=Mock();thread.start.side_effect=RuntimeError('SECRET start failure')
            worker.thread_factory=Mock(return_value=thread)
            request=BackupRequest('a'*32,'NEW')
            with self.assertRaises(RuntimeError): worker.submit(request)
            self.assertEqual(worker.journal.current()['state'],'FAILED')
            self.assertEqual(worker.submit(request).request_id,request.request_id)
            bf.assert_not_called();rf.assert_not_called();self.assertEqual(api.present,set())
            self.assertFalse(worker.thread_factory.call_args.kwargs['daemon'])
            with operation_lock(worker.state):pass

    def test_mismatched_coordinator_scope_and_unverified_return_never_become_success(self):
        for change in ('scope','return'):
            with self.subTest(change=change), self.fixture() as (worker,api,store,history,progress,root,entered,release,bf,rf,write):
                real=bf.side_effect
                def factory():
                    coordinator=real()
                    if change=='scope':coordinator.dataset='another/config'
                    else:coordinator.run_new=Mock(return_value=NAME)
                    return coordinator
                bf.side_effect=factory
                worker.submit(BackupRequest('a'*32,'NEW'));worker.close()
                self.assertEqual(worker.journal.current()['state'],'FAILED')
                self.assertEqual(api.present,set())
                self.assertFalse(any(method=='pool.snapshot.create' for method,args in api.calls))

    def test_borrowed_lock_cannot_be_reused_redirected_or_used_from_another_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory).resolve();borrowed=_BorrowedGuard(state)
            with self.assertRaises(OperationDenied):
                with borrowed(state):pass
            borrowed.owner=threading.get_ident()
            with self.assertRaises(OperationDenied):
                with borrowed(state/'other'):pass
            with borrowed(state):pass
            with self.assertRaises(OperationDenied):
                with borrowed(state):pass

    def test_admission_interruption_blocks_cancel_without_faking_a_restore_outcome(self):
        with self.fixture() as (worker,api,store,history,progress,root,entered,release,bf,rf,write):
            request=self.prepare_restore(worker,api,root,store,history)
            rf.side_effect=KeyboardInterrupt()
            worker.submit(request);worker.close()
            self.assertEqual(worker.journal.current()['state'],'RECOVERY_REQUIRED')
            with store.transaction() as operation:
                self.assertIsNone(operation.outcome)
                self.assertEqual(operation.phase,Phase.WAITING_FOR_PLEX_STOP)
            web=Web(worker.state,worker.destination,api,execution_service=worker.gateway())
            token,csrf=web.sessions.create();payload=b'{}';responses=[]
            body=b''.join(web({'REQUEST_METHOD':'POST','PATH_INFO':'/api/restore/cancel',
                'CONTENT_TYPE':'application/json','CONTENT_LENGTH':'2','wsgi.input':io.BytesIO(payload),
                'HTTP_COOKIE':'pcc_session='+token,'HTTP_X_CSRF_TOKEN':csrf},
                lambda status,headers:responses.append(status)))
            self.assertEqual(responses,['409 Conflict'])
            write.assert_not_called()
            self.assertIsNone(worker.gateway().status().get('owner_hash'))

    def test_legacy_operation_records_load_without_a_bound_execution_id(self):
        with tempfile.TemporaryDirectory() as directory:
            store=StateStore(directory)
            with store._connect() as db:
                payload=json.loads(db.execute('SELECT payload FROM operation WHERE id=1').fetchone()[0])
                payload.pop('execution_request_id')
                db.execute('UPDATE operation SET payload=? WHERE id=1',(json.dumps(payload),))
            with StateStore(directory).transaction() as operation:
                self.assertIsNone(operation.execution_request_id)
                operation.execution_request_id='a'*32
                operation.begin('BACKUP')
                self.assertIsNone(operation.execution_request_id)

    def test_owner_startup_marks_abandoned_admission_without_running_factories(self):
        with self.fixture() as (worker,api,store,history,progress,root,entered,release,bf,rf,write):
            request=BackupRequest('a'*32,'NEW')
            worker.journal.reserve(request)
            result=worker.reconcile_startup()
            self.assertEqual(result['requests'],['a'*32])
            self.assertEqual(worker.journal.current()['state'],'RECOVERY_REQUIRED')
            self.assertEqual(worker.reconcile_startup()['requests'],[])
            bf.assert_not_called();rf.assert_not_called()
            with self.assertRaises(OperationBusy):worker.submit(BackupRequest('b'*32,'NEW'))

    def test_live_job_cannot_be_reconciled_as_an_interruption(self):
        with self.fixture(blocked=True) as (worker,api,store,history,progress,root,entered,release,bf,rf,write):
            worker.submit(BackupRequest('a'*32,'NEW'));self.assertTrue(entered.wait(3))
            with self.assertRaises(OperationBusy):worker.reconcile_startup()
            self.assertEqual(worker.journal.current()['state'],'RUNNING')
            release.set();worker.close()
            self.assertEqual(worker.journal.current()['state'],'SUCCEEDED')
