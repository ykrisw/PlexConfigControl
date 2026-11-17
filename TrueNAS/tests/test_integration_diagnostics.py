"""Read-only diagnostics use scoped adapters and never probe by creating data."""
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

from plexconfigcontrol.archive_store import ArchiveStore
from plexconfigcontrol.history import History
from plexconfigcontrol.integration_diagnostics import inspect_integration
from plexconfigcontrol.locking import operation_lock
from plexconfigcontrol.operations import Phase
from plexconfigcontrol.plex import PlexStatus
from plexconfigcontrol.recovery import Recovery
from plexconfigcontrol.runtime import ReadOnlyTrueNAS, Configuration, prepare
from plexconfigcontrol.installation import password_verifier
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.web import Web

DATASET='test/config'
SNAPSHOT=DATASET+'@pcc-backup-'+'a'*32
ARCHIVE='TrueNASPlexConfig_2026.11.03_12.00.00.tar.gz'


class IntegrationDiagnosticsTests(unittest.TestCase):
    def test_missing_configuration_never_implies_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            result=inspect_integration(StateStore(directory))
            self.assertEqual(result['plex']['state'],'NOT_CONFIGURED')
            self.assertEqual(result['archives']['state'],'NOT_CONFIGURED')
            self.assertEqual(result['snapshot']['state'],'NOT_CONFIGURED')
            self.assertFalse(result['backup_available']);self.assertFalse(result['restore_available'])

    def test_archive_listing_never_validates_imports_or_changes_permanent_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archives=root/'archives';(archives/'Logs').mkdir(parents=True)
            file=archives/ARCHIVE;file.write_bytes(b'not an archive; metadata only')
            log=archives/'Logs'/'keep.log';log.write_bytes(b'permanent')
            store=StateStore(root/'state');history=History(root/'state')
            with store.transaction() as operation:before=asdict(operation)
            with patch('plexconfigcontrol.archives.validate_archive',side_effect=AssertionError('Must not read file content')):
                result=inspect_integration(store,ArchiveStore(archives,root/'state'))
            self.assertEqual(result['archives'],{'configured':True,'state':'LIST_VERIFIED','count':1})
            self.assertEqual(file.read_bytes(),b'not an archive; metadata only')
            self.assertEqual(log.read_bytes(),b'permanent');self.assertEqual(history.list(),[])
            self.assertEqual(len(list((archives/'Logs').iterdir())),1)
            with store.transaction() as operation:self.assertEqual(asdict(operation),before)

    def test_configured_snapshot_scope_with_no_record_does_not_probe_snapshot_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            inspector=Mock(side_effect=AssertionError('No snapshot query without a record'))
            result=inspect_integration(StateStore(directory),snapshot_inspector=inspector)
            self.assertEqual(result['snapshot']['state'],'NO_RECORDED_SNAPSHOT')
            inspector.assert_not_called()

    def test_only_plex_and_exact_recorded_snapshot_are_queried(self):
        with tempfile.TemporaryDirectory() as directory:
            store=StateStore(directory);history=History(directory)
            with store.transaction() as operation:
                operation.kind='BACKUP';operation.phase=Phase.RECOVERY_REQUIRED;operation.snapshot_id=SNAPSHOT
            client=Mock()
            def call(method,*args):
                if method=='pool.snapshot.query':return [{'id':SNAPSHOT}]
                if method=='app.query':return [{'name':'plex','state':'RUNNING'}]
                raise AssertionError('Unexpected API method')
            client.call.side_effect=call;api=ReadOnlyTrueNAS(client,DATASET)
            result=inspect_integration(store,plex=PlexStatus(api),
                snapshot_inspector=Recovery(api,store,history,directory,DATASET).inspect)
            self.assertEqual(result['plex']['state'],'READ_VERIFIED')
            self.assertEqual(result['snapshot']['state'],'PRESENT')
            self.assertEqual(result['operation']['state'],'RECOVERY_REQUIRED')
            self.assertFalse(result['backup_available']);self.assertFalse(result['restore_available'])
            self.assertEqual(client.call.call_args_list[0].args,('pool.snapshot.query',[['id','=',SNAPSHOT]]))
            self.assertEqual(client.call.call_args_list[1].args,('app.query',[['name','=','plex']],{'select':['name','state']}))
            self.assertEqual(client.call.call_count,2)
            self.assertNotIn(SNAPSHOT,json.dumps(result))

    def test_permission_or_network_errors_are_sanitized_and_not_inferred_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            store=StateStore(directory)
            with store.transaction() as operation:
                operation.kind='RESTORE';operation.phase=Phase.RECOVERY_REQUIRED;operation.snapshot_id=SNAPSHOT
            api=Mock();api.call.side_effect=PermissionError('private secret /credential/file')
            result=inspect_integration(store,plex=PlexStatus(api),
                snapshot_inspector=Mock(side_effect=TimeoutError('private secret API key')))
            self.assertEqual(result['plex']['state'],'UNAVAILABLE')
            self.assertEqual(result['snapshot']['state'],'UNKNOWN')
            self.assertNotIn('secret',json.dumps(result));self.assertNotIn('credential',json.dumps(result))

    def test_busy_operation_skips_all_external_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            store=StateStore(directory);archives=Mock();plex=Mock();snapshot=Mock()
            with operation_lock(directory):result=inspect_integration(store,archives,plex,snapshot)
            self.assertEqual(result['operation']['state'],'BUSY')
            archives.list.assert_not_called();plex.read.assert_not_called();snapshot.assert_not_called()

    def test_changed_operation_clears_snapshot_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            store=StateStore(directory)
            with store.transaction() as operation:
                operation.kind='RESTORE';operation.phase=Phase.RECOVERY_REQUIRED;operation.snapshot_id=SNAPSHOT
            inspector=Mock(return_value={'kind':'RESTORE','phase':'RECOVERY_REQUIRED','snapshot_id':SNAPSHOT,'snapshot_state':'PRESENT'})
            def plex_read():
                with store.transaction() as operation:operation.snapshot_id=None
                return {'state':'STOPPED','available':True}
            plex=Mock();plex.read.side_effect=plex_read
            result=inspect_integration(store,plex=plex,snapshot_inspector=inspector)
            self.assertEqual(result['operation']['state'],'CHANGED')
            self.assertEqual(result['snapshot']['state'],'UNKNOWN')

    def test_active_record_is_not_mislabeled_failed_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store=StateStore(directory)
            with store.transaction() as operation:
                operation.kind='BACKUP';operation.phase=Phase.RUNNING;operation.snapshot_id=SNAPSHOT
            inspector=Mock()
            result=inspect_integration(store,snapshot_inspector=inspector)
            self.assertEqual(result['operation']['state'],'ACTIVE')
            self.assertEqual(result['snapshot']['state'],'NOT_CHECKED');inspector.assert_not_called()

    def test_authenticated_runtime_get_is_allowed_but_post_cannot_change_configuration(self):
        from test_runtime import RuntimeTests
        with tempfile.TemporaryDirectory() as directory:
            app,_,_=prepare(Configuration(Path(directory),'localhost'),password_verifier('fixture-password'))
            helper=RuntimeTests()
            self.assertEqual(helper.request(app,'/api/integration')[0],'401 Unauthorized')
            token,csrf=app.web.sessions.create();cookie='pcc_session='+token
            status,_,body=helper.request(app,'/api/integration',cookie=cookie)
            self.assertEqual(status,'200 OK');self.assertFalse(json.loads(body)['restore_available'])
            self.assertEqual(helper.request(app,'/api/integration','POST',{},cookie,csrf)[0],'403 Forbidden')
            self.assertEqual(helper.request(app.web,'/api/integration','POST',{},cookie,csrf)[0],'404 Not Found')
            self.assertEqual(app.web.history.list(),[])
