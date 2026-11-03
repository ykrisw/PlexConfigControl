import io
import json
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock

from plexconfigcontrol.execution import ExecutionGateway, BackupRequest, RestoreRequest, AcceptedOperation
from plexconfigcontrol.archive_store import ArchiveStore
from plexconfigcontrol.backup_archive import create_archive
from plexconfigcontrol.restore_validation import RestoreValidation
from plexconfigcontrol.runtime import TestApplication
from plexconfigcontrol.web import Web, archive_wire
from tests.host_snapshot_smoke import archive_fixture

REQUEST_ID = 'a'*32
NAME = 'TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'


class ExecutionTests(unittest.TestCase):
    @contextmanager
    def fixture(self, enabled=True):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root/'state'; destination = root/'Plex Config'
            (destination/'Logs').mkdir(parents=True)
            api = Mock(); api.call.return_value = [{'name':'plex','state':'RUNNING'}]
            backend = Mock()
            backend.submit.side_effect = lambda request: AcceptedOperation(
                request.request_id, 'BACKUP' if isinstance(request, BackupRequest) else 'RESTORE')
            gateway = ExecutionGateway(state, destination, api, backend) if enabled else None
            web = Web(state, destination, api, execution_service=gateway)
            token, csrf = web.sessions.create()
            yield web, backend, api, root, token, csrf

    def request(self, web, path, data=None, token=None, csrf=None):
        payload = json.dumps(data).encode() if data is not None else b''
        env = {'REQUEST_METHOD':'POST' if data is not None else 'GET', 'PATH_INFO':path,
               'CONTENT_TYPE':'application/json', 'CONTENT_LENGTH':str(len(payload)),
               'wsgi.input':io.BytesIO(payload)}
        if token: env['HTTP_COOKIE']='pcc_session='+token
        if csrf: env['HTTP_X_CSRF_TOKEN']=csrf
        result = []
        body = b''.join(web(env, lambda status, headers: result.append(status)))
        return result[0], json.loads(body)

    def test_new_backup_returns_only_submission_receipt_and_fixed_typed_request(self):
        with self.fixture() as (web, backend, api, root, token, csrf):
            code, body = self.request(web, '/api/backup/start',
                {'request_id':REQUEST_ID,'mode':'NEW','confirmed':True}, token, csrf)
            self.assertEqual(code,'202 Accepted')
            self.assertEqual(body,{'accepted':True,'request_id':REQUEST_ID,'kind':'BACKUP','status_url':'/api/operation'})
            self.assertEqual(backend.submit.call_args.args,(BackupRequest(REQUEST_ID,'NEW'),))
            self.assertEqual(web.history.list(),[])
            self.assertIsNone(web.progress.read())
            self.assertEqual(list((root/'Plex Config/Logs').iterdir()),[])

    def test_session_csrf_and_explicit_configuration_are_required(self):
        data={'request_id':REQUEST_ID,'mode':'NEW','confirmed':True}
        for enabled in (False,True):
            with self.fixture(enabled) as (web, backend, api, root, token, csrf):
                self.assertEqual(self.request(web,'/api/backup/start',data)[0],'401 Unauthorized')
                self.assertEqual(self.request(web,'/api/backup/start',data,token)[0],'403 Forbidden')
                if not enabled:
                    self.assertEqual(self.request(web,'/api/backup/start',data,token,csrf)[0],'403 Forbidden')
                    self.assertFalse(self.request(web,'/api/capabilities',token=token)[1]['backup_create'])
                else:
                    self.assertTrue(self.request(web,'/api/capabilities',token=token)[1]['backup_create'])
                    with self.assertRaises(ValueError): TestApplication(web)
                backend.submit.assert_not_called()

    def test_unknown_fields_commands_paths_and_missing_confirmation_never_submit(self):
        base={'request_id':REQUEST_ID,'mode':'NEW','confirmed':True}
        invalid=[{**base,'command':'zfs destroy something'}, {**base,'dataset':'other'},
                 {**base,'path':'/config'}, {**base,'confirmed':1},
                 {**base,'request_id':'../escape'}, {**base,'mode':'SHELL'},
                 {**base,'archive':None}]
        for data in invalid:
            with self.subTest(data=data),self.fixture() as (web, backend, api, root, token, csrf):
                self.assertEqual(self.request(web,'/api/backup/start',data,token,csrf)[0],'400 Bad Request')
                backend.submit.assert_not_called()

    def test_single_copy_requires_current_identity_and_stale_confirmation_is_rejected(self):
        with self.fixture() as (web, backend, api, root, token, csrf):
            archive=root/'Plex Config'/NAME; archive.write_bytes(b'old archive')
            row=archive_wire(asdict(ArchiveStore(archive.parent,web.state_directory).list()[0]))
            data={'request_id':REQUEST_ID,'mode':'NEW','confirmed':True}
            self.assertEqual(self.request(web,'/api/backup/start',data,token,csrf)[0],'409 Conflict')
            for mode in ('ANOTHER','OVERWRITE'):
                data={**data,'request_id':('a' if mode=='ANOTHER' else 'b')*32,'mode':mode,'archive':row}
                self.assertEqual(self.request(web,'/api/backup/start',data,token,csrf)[0],'202 Accepted')
                self.assertEqual(backend.submit.call_args.args[0].archive.name,NAME)
            backend.submit.reset_mock()
            archive.write_bytes(b'changed outside panel')
            self.assertEqual(self.request(web,'/api/backup/start',data,token,csrf)[0],'409 Conflict')
            backend.submit.assert_not_called()

    def test_wrong_or_unknown_plex_status_never_submits_backup(self):
        for response in ([{'name':'plex','state':'STOPPED'}],
                         [{'name':'other','state':'RUNNING'}],None):
            with self.subTest(response=response), self.fixture() as (web,backend,api,root,token,csrf):
                api.call.return_value=response
                code,_=self.request(web,'/api/backup/start',
                    {'request_id':REQUEST_ID,'mode':'NEW','confirmed':True},token,csrf)
                self.assertEqual(code,'409 Conflict');backend.submit.assert_not_called()

    def test_receipt_mismatch_or_lost_response_is_uncertain_without_retry_or_secret_leak(self):
        for receipt in (None, AcceptedOperation('b'*32,'BACKUP'), AcceptedOperation(REQUEST_ID,'RESTORE')):
            with self.subTest(receipt=receipt), self.fixture() as (web,backend,api,root,token,csrf):
                backend.submit.side_effect=None; backend.submit.return_value=receipt
                code,body=self.request(web,'/api/backup/start',
                    {'request_id':REQUEST_ID,'mode':'NEW','confirmed':True},token,csrf)
                self.assertEqual(code,'503 Service Unavailable');backend.submit.assert_called_once()
                self.assertNotIn('success',body)
        with self.fixture() as (web,backend,api,root,token,csrf):
            backend.submit.side_effect=TimeoutError('SECRET private transport path')
            code,body=self.request(web,'/api/backup/start',
                {'request_id':REQUEST_ID,'mode':'NEW','confirmed':True},token,csrf)
            self.assertEqual(code,'503 Service Unavailable');backend.submit.assert_called_once()
            self.assertNotIn('SECRET',json.dumps(body))

    def test_restore_requires_validated_unchanged_archive_digest_and_real_stopped_status(self):
        with self.fixture() as (web,backend,api,root,token,csrf):
            source=root/'fixture';source.mkdir();archive_fixture(source)
            destination=root/'Plex Config'
            create_archive(source,destination/NAME)
            validation=RestoreValidation(destination,web.state_directory,web.operation_store,web.history).validate(NAME)
            data={'request_id':REQUEST_ID,'archive':NAME,'sha256':validation['sha256'],'confirmation':'RESTORE'}
            self.assertEqual(self.request(web,'/api/restore/execute',data,token,csrf)[0],'409 Conflict')
            api.call.return_value=[{'name':'plex','state':'STOPPED'}]
            self.assertEqual(self.request(web,'/api/restore/execute',{**data,'sha256':'b'*64},token,csrf)[0],'409 Conflict')
            code,body=self.request(web,'/api/restore/execute',data,token,csrf)
            self.assertEqual(code,'202 Accepted')
            self.assertEqual(backend.submit.call_args.args,(RestoreRequest(REQUEST_ID,NAME,validation['sha256'],'RESTORE'),))
            backend.submit.reset_mock()
            (destination/NAME).write_bytes(b'externally replaced')
            self.assertEqual(self.request(web,'/api/restore/execute',data,token,csrf)[0],'409 Conflict')
            backend.submit.assert_not_called()

    def test_restore_wrong_confirmation_or_extra_fields_never_submit(self):
        base={'request_id':REQUEST_ID,'archive':NAME,'sha256':'b'*64,'confirmation':'RESTORE'}
        for data in ({**base,'confirmation':'yes'},{**base,'dataset':'other'},
                     {**base,'archive':'../../config'}, {**base,'sha256':'x'*64}):
            with self.subTest(data=data), self.fixture() as (web,backend,api,root,token,csrf):
                self.assertEqual(self.request(web,'/api/restore/execute',data,token,csrf)[0],'400 Bad Request')
                backend.submit.assert_not_called()

    def test_backend_cannot_use_another_panels_private_state_or_archive_directory(self):
        with self.fixture() as (web,backend,api,root,token,csrf):
            with self.assertRaises(ValueError):
                Web(root/'other-state',root/'Plex Config',api,execution_service=web.execution)

    def test_unresolved_operation_blocks_submission_even_with_valid_session_and_status(self):
        with self.fixture() as (web,backend,api,root,token,csrf):
            with web.operation_store.transaction() as operation:
                operation.begin('BACKUP');operation.begin_backup()
                operation.record_snapshot_intent('test/config','pcc-backup-'+'b'*32)
            code,_=self.request(web,'/api/backup/start',
                {'request_id':REQUEST_ID,'mode':'NEW','confirmed':True},token,csrf)
            self.assertEqual(code,'409 Conflict')
            backend.submit.assert_not_called()
