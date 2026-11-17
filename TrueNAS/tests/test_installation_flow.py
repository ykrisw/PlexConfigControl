import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from plexconfigcontrol.installation_flow import InstallationStorageFlow
from plexconfigcontrol.installation_storage import InstallationStoragePlan, plan_storage
from plexconfigcontrol.plex_storage import PlexStorage, StorageDiscoveryError
from plexconfigcontrol.storage import RenameRequired


class InstallationFlowTests(unittest.TestCase):
    def plan(self,parent='/mnt/tank/backups'):
        return InstallationStoragePlan(parent,PlexStorage('host_path','/mnt/tank/plex','tank/plex','/mnt/tank/plex','.'))

    def test_failed_auto_detection_manual_retry_and_exact_confirmation(self):
        with patch('plexconfigcontrol.installation_flow.plan_storage',side_effect=[StorageDiscoveryError('PLEX_STORAGE_READ_FAILED'),self.plan()]) as plan,patch('plexconfigcontrol.installation_flow.create_storage') as create:
            flow=InstallationStorageFlow(Mock(),'pl')
            failed=flow.check('/mnt/tank/backups')
            self.assertEqual(failed['phase'],'MANUAL_REQUIRED');self.assertTrue(failed['error']['manual_entry_available'])
            ready=flow.check('/mnt/tank/backups',manual_source='/mnt/tank/plex')
            self.assertEqual(ready['phase'],'READY');create.assert_not_called()
            flow.create(ready['revision']);flow.create('stale',confirmed=True);create.assert_not_called()
            done=flow.create(ready['revision'],confirmed=True)
            self.assertEqual(done['phase'],'COMPLETE')
            flow.create(ready['revision'],confirmed=True);flow.check('/mnt/changed')
            create.assert_called_once();self.assertEqual(plan.call_count,2)

    def test_changed_input_invalidates_old_confirmation(self):
        with patch('plexconfigcontrol.installation_flow.plan_storage',side_effect=[self.plan(),self.plan('/mnt/other')]),patch('plexconfigcontrol.installation_flow.create_storage') as create:
            flow=InstallationStorageFlow(Mock());old=flow.check('/mnt/tank/backups');new=flow.check('/mnt/other')
            flow.create(old['revision'],confirmed=True);create.assert_not_called()
            flow.create(new['revision'],confirmed=True);create.assert_called_once()
            self.assertEqual(create.call_args.args[1].parent,'/mnt/other')

    def test_ambiguous_write_failure_cannot_retry_or_adopt_partial_folder(self):
        with patch('plexconfigcontrol.installation_flow.plan_storage',return_value=self.plan()) as plan,patch('plexconfigcontrol.installation_flow.create_storage',side_effect=RuntimeError('secret raw failure')) as create:
            flow=InstallationStorageFlow(Mock());ready=flow.check('/mnt/tank/backups')
            result=flow.create(ready['revision'],confirmed=True)
            self.assertEqual(result['phase'],'REVIEW_REQUIRED');self.assertNotIn('secret',str(result))
            flow.create(ready['revision'],confirmed=True);flow.check('/mnt/tank/backups')
            create.assert_called_once();plan.assert_called_once()

    def test_existing_folder_reports_rename_before_ready_without_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'Plex Backup';root.mkdir();marker=root/'keep';marker.write_text('keep')
            mode=root.stat().st_mode
            with patch('plexconfigcontrol.installation_storage.discover_plex_storage',return_value=self.plan().plex):
                flow=InstallationStorageFlow(Mock(),'pl')
                result=flow.check(tmp)
                self.assertEqual(result['phase'],'RENAME_REQUIRED');self.assertFalse(result['can_create'])
                self.assertEqual(marker.read_text(),'keep');self.assertEqual(root.stat().st_mode,mode)
                root.rename(Path(tmp)/'Old Plex Backup')
                self.assertEqual(flow.check(tmp)['phase'],'READY')
                self.assertFalse(root.exists())  # Checking never creates directories.

    def test_failed_recheck_never_creates_after_storage_reconfiguration(self):
        with patch('plexconfigcontrol.installation_flow.plan_storage',return_value=self.plan()),patch('plexconfigcontrol.installation_flow.create_storage',side_effect=StorageDiscoveryError('PLEX_STORAGE_CHANGED')) as create:
            flow=InstallationStorageFlow(Mock());ready=flow.check('/mnt/tank/backups')
            result=flow.create(ready['revision'],confirmed=True)
            self.assertEqual(result['phase'],'MANUAL_REQUIRED');self.assertIsNone(result['revision'])
            flow.create(ready['revision'],confirmed=True);create.assert_called_once()

    def test_view_cannot_modify_trusted_plan_or_confirmation(self):
        with patch('plexconfigcontrol.installation_flow.plan_storage',return_value=self.plan()):
            flow=InstallationStorageFlow(Mock());view=flow.check('/mnt/tank/backups')
            view['storage']['source']='/mnt/other';view['revision']='bad'
            self.assertEqual(flow.view()['storage']['source'],'/mnt/tank/plex')
            self.assertNotEqual(flow.view()['revision'],'bad')


    def test_approved_copy_and_preview_are_host_free_and_invalidate_previous_check(self):
        from datetime import datetime, timezone
        from plexconfigcontrol.installation_flow import installation_preview, installation_fields
        fields={field['name']:field for field in installation_fields('pl')}
        self.assertEqual(fields['parent']['label'],'Miejsce przechowywania kopii zapasowych Plex')
        self.assertIn('bezpośrednio dataset',fields['parent']['description'])
        self.assertEqual(fields['folder_name']['label'],'Nazwa nowego folderu na kopie i logi')
        preview=installation_preview('/mnt/Archiwum/Kopie',language='pl',instant=datetime(2026,11,4,10,20,30,tzinfo=timezone.utc))
        self.assertEqual(preview['folder'],'/mnt/Archiwum/Kopie/Plex Backup')
        self.assertEqual(preview['logs'],'/mnt/Archiwum/Kopie/Plex Backup/Logs')
        self.assertEqual(preview['archive'],'PlexConfig_2026.11.04_10.20.30.tar.gz')
        self.assertTrue(preview['example']);self.assertFalse(preview['checked']);self.assertFalse(preview['created'])
        api=Mock()
        with patch('plexconfigcontrol.installation_flow.plan_storage',return_value=self.plan()) as plan,patch('plexconfigcontrol.installation_flow.create_storage') as create:
            flow=InstallationStorageFlow(api,'pl');ready=flow.check('/mnt/tank/backups')
            edited=flow.edit('/mnt/Pool_B',folder_name='Moje kopie',archive_prefix='Dupa')
            self.assertEqual(edited['preview']['folder'],'/mnt/Pool_B/Moje kopie')
            self.assertTrue(edited['preview']['archive'].startswith('Dupa_'))
            self.assertFalse(edited['can_create']);self.assertIsNone(edited['revision'])
            flow.create(ready['revision'],confirmed=True)
            create.assert_not_called();api.call.assert_not_called();plan.assert_called_once()
            invalid=flow.edit('../wrong')
            self.assertIsNone(invalid['preview'])
            self.assertIsNone(invalid['storage'])
