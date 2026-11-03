import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from plexconfigcontrol.runtime import Configuration, ReadOnlyTrueNAS, prepare
from plexconfigcontrol.installation import password_verifier
from plexconfigcontrol.operations import Phase

DATASET='test/config'
IDENTIFIER=DATASET+'@pcc-backup-'+'a'*32


class ScopedSnapshotReadTests(unittest.TestCase):
    def test_only_exact_app_snapshot_queries_in_explicit_scope_are_forwarded(self):
        client=Mock();client.call.return_value=[{'id':IDENTIFIER}]
        adapter=ReadOnlyTrueNAS(client,DATASET)
        self.assertEqual(adapter.call('pool.snapshot.query',[['id','=',IDENTIFIER]]),[{'id':IDENTIFIER}])
        client.call.assert_called_once_with('pool.snapshot.query',[['id','=',IDENTIFIER]])

    def test_no_scope_keeps_all_snapshot_reads_disabled(self):
        client=Mock()
        with self.assertRaises(PermissionError):ReadOnlyTrueNAS(client).call('pool.snapshot.query',[['id','=',IDENTIFIER]])
        client.call.assert_not_called()

    def test_broad_or_external_filters_and_extra_options_are_rejected_without_network_io(self):
        client=Mock();adapter=ReadOnlyTrueNAS(client,DATASET)
        requests=[(),([],),([['id','!=',IDENTIFIER]],),([['dataset','=',DATASET]],),
                  ([['id','=','other/config@pcc-backup-'+'a'*32]],),
                  ([['id','=',DATASET+'@manual-snapshot']],),([['id','=',None]],),
                  ([['id','=',IDENTIFIER]],{'recursive':True}),
                  ([['id','=',IDENTIFIER],['id','=','another']],)]
        for args in requests:
            with self.subTest(args=args):
                with self.assertRaises(PermissionError):adapter.call('pool.snapshot.query',*args)
        client.call.assert_not_called()

    def test_read_scope_never_grants_any_snapshot_or_app_mutation(self):
        client=Mock();adapter=ReadOnlyTrueNAS(client,DATASET)
        for method in ('app.stop','app.start','app.delete','pool.snapshot.create',
                       'pool.snapshot.delete','pool.snapshot.rollback','filesystem.setacl'):
            with self.subTest(method=method):
                with self.assertRaises(PermissionError):adapter.call(method,IDENTIFIER)
        client.call.assert_not_called()

    def test_configuration_requires_connection_and_validates_dataset_before_use(self):
        for dataset in ('','../config','pool//config','pool/config@name','pool/config\n',True):
            with self.subTest(dataset=dataset):
                with self.assertRaises(ValueError):
                    Configuration(Path('/tmp/test'),'localhost',truenas_url='wss://example/api/current',
                                  api_username='test',api_key_file='/private/key',snapshot_dataset=dataset)
        with self.assertRaises(ValueError):
            Configuration.from_environment({'PCC_PUBLIC_HOST':'localhost','PCC_PLEX_CONFIG_DATASET':DATASET})
        config=Configuration.from_environment({'PCC_PUBLIC_HOST':'localhost','PCC_PLEX_CONFIG_DATASET':DATASET,
            'PCC_TRUENAS_URL':'wss://example/api/current','PCC_API_USERNAME':'test','PCC_API_KEY_FILE':'/private/key'})
        self.assertEqual(config.snapshot_dataset,DATASET)

    def test_runtime_connects_verified_inspector_but_all_mutations_remain_blocked(self):
        from test_runtime import RuntimeTests
        with tempfile.TemporaryDirectory() as directory:
            client=Mock();client.call.return_value=[{'id':IDENTIFIER}]
            config=Configuration(Path(directory),'localhost',truenas_url='wss://example/api/current',
                api_username='test',api_key_file='/private/key',snapshot_dataset=DATASET)
            with patch('plexconfigcontrol.runtime.build_client',return_value=client) as factory,patch('plexconfigcontrol.runtime.read_secret',return_value='ci-only-key'):
                app,_,_=prepare(config,password_verifier('ci-only-password'))
            factory.assert_called_once_with('wss://example/api/current','test','ci-only-key',None,timeout=10)
            with app.web.operation_store.transaction() as operation:
                operation.kind='BACKUP';operation.phase=Phase.RECOVERY_REQUIRED;operation.snapshot_id=IDENTIFIER
            token,_=app.web.sessions.create()
            helper=RuntimeTests()
            status,_,body=helper.request(app,'/api/recovery',cookie='pcc_session='+token)
            self.assertEqual(status,'200 OK');result=json.loads(body)
            self.assertEqual(result['snapshot_state'],'PRESENT')
            self.assertFalse(result['removal_supported']);self.assertFalse(result['removal_available'])
            client.call.assert_called_once_with('pool.snapshot.query',[['id','=',IDENTIFIER]])
            for route in ('/api/snapshots/delete','/api/recovery','/api/backup/start','/api/restore/execute'):
                self.assertEqual(helper.request(app,route,'POST',{})[0],'403 Forbidden')
            client.call.reset_mock();client.call.return_value=None
            self.assertEqual(json.loads(helper.request(app,'/api/recovery',cookie='pcc_session='+token)[2])['snapshot_state'],'UNKNOWN')
            with app.web.operation_store.transaction() as operation:self.assertEqual(operation.snapshot_id,IDENTIFIER)
