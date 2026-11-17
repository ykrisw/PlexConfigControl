import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from plexconfigcontrol.execution import ExecutionGateway, BackupRequest
from plexconfigcontrol.execution_journal import ExecutionJournal
from plexconfigcontrol.web import Web


class ExecutionStatusTests(unittest.TestCase):
    def request(self,web,query,token=None):
        response=[]
        env={'REQUEST_METHOD':'GET','PATH_INFO':'/api/execution/status',
             'QUERY_STRING':query,'wsgi.input':io.BytesIO()}
        if token:env['HTTP_COOKIE']='pcc_session='+token
        body=b''.join(web(env,lambda status,headers:response.append(status)))
        return response[0],json.loads(body)

    def test_exact_request_status_is_authenticated_and_does_not_execute_or_expose_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);state=root/'state';destination=root/'Plex Config';destination.mkdir()
            journal=ExecutionJournal(state);request=BackupRequest('a'*32,'NEW');journal.reserve(request)
            journal.claim(request)
            backend=Mock();api=Mock();lookup=Mock(wraps=journal.status)
            gateway=ExecutionGateway(state,destination,api,backend,status_lookup=lookup)
            web=Web(state,destination,api,execution_service=gateway);token,_=web.sessions.create()
            query='request_id='+request.request_id
            self.assertEqual(self.request(web,query)[0],'401 Unauthorized');lookup.assert_not_called()
            code,result=self.request(web,query,token)
            self.assertEqual(code,'200 OK');self.assertTrue(result['found'])
            self.assertEqual(result['execution']['request_id'],request.request_id)
            self.assertEqual(result['execution']['state'],'RUNNING')
            self.assertEqual(set(result['execution']),{'request_id','kind','state','created_ns','updated_ns'})
            self.assertIsInstance(result['execution']['updated_ns'],str)
            self.assertEqual(self.request(web,'request_id='+'b'*32,token),('200 OK',{'found':False,'execution':None}))
            backend.submit.assert_not_called();api.call.assert_not_called()

    def test_invalid_duplicate_or_extra_query_fields_never_reach_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);destination=root/'Plex Config';destination.mkdir();lookup=Mock()
            gateway=ExecutionGateway(root/'state',destination,Mock(),Mock(),status_lookup=lookup)
            web=Web(root/'state',destination,execution_service=gateway);token,_=web.sessions.create()
            for query in ('','request_id=../config','request_id='+'a'*32+'&request_id='+'b'*32,
                          'request_id='+'a'*32+'&command=anything'):
                with self.subTest(query=query):self.assertEqual(self.request(web,query,token)[0],'400 Bad Request')
            lookup.assert_not_called()

    def test_wrong_identity_private_fields_or_unavailable_reader_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);destination=root/'Plex Config';destination.mkdir()
            lookup=Mock();gateway=ExecutionGateway(root/'state',destination,Mock(),Mock(),status_lookup=lookup)
            web=Web(root/'state',destination,execution_service=gateway);token,_=web.sessions.create()
            valid={'request_id':'a'*32,'kind':'BACKUP','state':'RUNNING','created_ns':'1','updated_ns':'2'}
            for value in ({**valid,'request_id':'b'*32},{**valid,'owner_hash':'SECRET'},{}):
                lookup.return_value=value
                code,result=self.request(web,'request_id='+'a'*32,token)
                self.assertEqual(code,'503 Service Unavailable');self.assertNotIn('SECRET',json.dumps(result))
            gateway.status_lookup=None
            self.assertEqual(self.request(web,'request_id='+'a'*32,token)[0],'503 Service Unavailable')

    def test_restricted_default_web_does_not_expose_execution_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            web=Web(directory);token,_=web.sessions.create()
            self.assertEqual(self.request(web,'request_id='+'a'*32,token)[0],'403 Forbidden')
