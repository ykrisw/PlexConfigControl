import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from plexconfigcontrol.auth import Account
from plexconfigcontrol.installation import password_verifier, initialize_from_verifier
from plexconfigcontrol.installation_service import InstallationService, InstallationDenied
from plexconfigcontrol.plex_storage import PlexStorage
from plexconfigcontrol.sessions import Sessions
from plexconfigcontrol.state import StateStore
from plexconfigcontrol.operations import Phase


class InstallationServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.verifier=password_verifier('test-only-password')

    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'private';state.mkdir();destination=root/'Backups';destination.mkdir()
            account=Account(state);initialize_from_verifier(account,self.verifier);sessions=Sessions(state,account)
            token,csrf=sessions.create();api=Mock()
            service=InstallationService(api,sessions,state,'pl')
            source=PlexStorage('host_path','/mnt/apps/plex','apps/plex','/mnt/apps/plex','.')
            with patch('plexconfigcontrol.installation_storage.discover_plex_storage',return_value=source):
                yield service,sessions,token,csrf,api,state,destination

    def test_auth_csrf_and_exact_fields_are_required_before_host_reads(self):
        with self.fixture() as (service,_,token,csrf,api,_,destination):
            for bad_token,bad_csrf,payload in [('invalid',csrf,{'parent':str(destination)}),(token,'wrong',{'parent':str(destination)}),(token,csrf,{'parent':str(destination),'command':'stop Plex'})]:
                with self.assertRaises(InstallationDenied):service.check(bad_token,bad_csrf,payload)
            api.call.assert_not_called();self.assertEqual(list(destination.iterdir()),[])

    def test_real_setup_persists_names_and_duplicate_confirmation_only_returns_receipt(self):
        with self.fixture() as (service,sessions,token,csrf,api,state,destination):
            ready=service.check(token,csrf,{'parent':str(destination),'folder_name':'Moje kopie','archive_prefix':'Dupa'})
            self.assertEqual(ready['phase'],'READY');self.assertEqual(list(destination.iterdir()),[])
            request={'revision':ready['revision'],'confirmed':True}
            done=service.create(token,csrf,request);self.assertEqual(done['phase'],'COMPLETE')
            self.assertTrue((destination/'Moje kopie'/'Logs').is_dir())
            marker=destination/'Moje kopie'/'external';marker.write_bytes(b'keep')
            restarted=InstallationService(api,sessions,state,'pl')
            self.assertEqual(restarted.status(token)['phase'],'COMPLETE')
            self.assertEqual(restarted.create(token,csrf,request)['phase'],'COMPLETE')
            self.assertEqual(marker.read_bytes(),b'keep')
            self.assertEqual(json.loads((state/'output-naming.json').read_text())['archive_prefix'],'Dupa')
            self.assertEqual((state/'installation.sqlite3').stat().st_mode&0o077,0)
            with self.assertRaises(InstallationDenied):restarted.check(token,csrf,{'parent':str(destination)})

    def test_second_session_cannot_consume_checked_plan_or_see_revision(self):
        with self.fixture() as (service,sessions,token,csrf,_,_,destination):
            ready=service.check(token,csrf,{'parent':str(destination)})
            other,other_csrf=sessions.create()
            self.assertIsNone(service.status(other)['revision'])
            with self.assertRaises(InstallationDenied):service.check(other,other_csrf,{'parent':str(destination)})
            with self.assertRaises(InstallationDenied):service.create(other,other_csrf,{'revision':ready['revision'],'confirmed':True})
            self.assertEqual(list(destination.iterdir()),[])

    def test_crash_after_durable_admission_never_replays_on_restart(self):
        with self.fixture() as (service,sessions,token,csrf,api,state,destination):
            ready=service.check(token,csrf,{'parent':str(destination)})
            with patch.object(service._flow,'create',side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    service.create(token,csrf,{'revision':ready['revision'],'confirmed':True})
            restarted=InstallationService(api,sessions,state)
            self.assertEqual(restarted.status(token)['phase'],'REVIEW_REQUIRED')
            with self.assertRaises(InstallationDenied):restarted.check(token,csrf,{'parent':str(destination)})
            self.assertEqual(list(destination.iterdir()),[])

    def test_safe_existing_folder_rejection_can_be_rechecked_after_manual_rename(self):
        with self.fixture() as (service,_,token,csrf,_,_,destination):
            ready=service.check(token,csrf,{'parent':str(destination)})
            existing=destination/'Plex Backup';existing.mkdir();(existing/'keep').write_bytes(b'keep')
            result=service.create(token,csrf,{'revision':ready['revision'],'confirmed':True})
            self.assertEqual(result['phase'],'RENAME_REQUIRED')
            existing.rename(destination/'Old backup')
            next_plan=service.check(token,csrf,{'parent':str(destination)})
            self.assertEqual(next_plan['phase'],'READY')
            self.assertEqual(service.status(token)['revision'],next_plan['revision'])
            self.assertEqual((destination/'Old backup'/'keep').read_bytes(),b'keep')

    def test_two_service_instances_cannot_both_create_different_output_folders(self):
        with self.fixture() as (first,sessions,token,csrf,api,state,destination):
            second=InstallationService(api,sessions,state)
            first_plan=first.check(token,csrf,{'parent':str(destination),'folder_name':'First'})
            second_plan=second.check(token,csrf,{'parent':str(destination),'folder_name':'Second'})
            self.assertEqual(first.create(token,csrf,{'revision':first_plan['revision'],'confirmed':True})['phase'],'COMPLETE')
            with self.assertRaises(InstallationDenied):second.create(token,csrf,{'revision':second_plan['revision'],'confirmed':True})
            self.assertEqual([p.name for p in destination.iterdir()],['First'])

    def test_persisted_core_recovery_state_blocks_installation(self):
        with self.fixture() as (service,_,token,csrf,_,state,destination):
            with StateStore(state).transaction() as operation:
                operation.phase=Phase.RECOVERY_REQUIRED;operation.snapshot_id='apps/plex@point'
            with self.assertRaises(InstallationDenied):service.check(token,csrf,{'parent':str(destination)})
            self.assertEqual(list(destination.iterdir()),[])

    def test_corrupt_completed_receipt_is_review_not_success(self):
        with self.fixture() as (service,_,token,csrf,_,state,destination):
            ready=service.check(token,csrf,{'parent':str(destination)})
            service.create(token,csrf,{'revision':ready['revision'],'confirmed':True})
            with sqlite3.connect(state/'installation.sqlite3') as db:
                db.execute("UPDATE installation SET receipt='broken'")
            self.assertEqual(service.status(token)['phase'],'REVIEW_REQUIRED')


    def test_failure_saving_receipt_after_real_folder_creation_retains_review_state(self):
        with self.fixture() as (service,sessions,token,csrf,api,state,destination):
            ready=service.check(token,csrf,{'parent':str(destination)})
            original=service._db;calls=0
            @contextmanager
            def failing_database():
                nonlocal calls
                calls+=1
                if calls==3:raise RuntimeError('simulated final receipt failure')
                with original() as db:yield db
            with patch.object(service,'_db',failing_database):
                with self.assertRaisesRegex(InstallationDenied,'UNCONFIRMED'):
                    service.create(token,csrf,{'revision':ready['revision'],'confirmed':True})
            self.assertTrue((destination/'Plex Backup'/'Logs').is_dir())
            external=destination/'Plex Backup'/'external';external.write_bytes(b'keep')
            restarted=InstallationService(api,sessions,state)
            self.assertEqual(restarted.status(token)['phase'],'REVIEW_REQUIRED')
            with self.assertRaises(InstallationDenied):restarted.create(token,csrf,{'revision':ready['revision'],'confirmed':True})
            self.assertEqual(external.read_bytes(),b'keep')
            self.assertNotIn(token.encode(),(state/'installation.sqlite3').read_bytes())


    def test_busy_core_lock_blocks_setup_without_disclosing_paths(self):
        from plexconfigcontrol.locking import operation_lock
        with self.fixture() as (service,_,token,csrf,_,state,destination):
            with operation_lock(state):
                with self.assertRaisesRegex(InstallationDenied,'INSTALLATION_BUSY'):
                    service.check(token,csrf,{'parent':str(destination)})
            self.assertEqual(list(destination.iterdir()),[])

    def test_unexpected_private_error_is_sanitized_and_logout_blocks_confirmation(self):
        with self.fixture() as (service,sessions,token,csrf,_,_,destination):
            with patch.object(service,'_record',side_effect=RuntimeError('credential=SECRET')):
                with self.assertRaisesRegex(InstallationDenied,'^INSTALLATION_UNAVAILABLE$'):
                    service.status(token)
            ready=service.check(token,csrf,{'parent':str(destination)})
            sessions.logout(token)
            with self.assertRaisesRegex(InstallationDenied,'SIGN_IN_REQUIRED'):
                service.create(token,csrf,{'revision':ready['revision'],'confirmed':True})
            self.assertEqual(list(destination.iterdir()),[])
