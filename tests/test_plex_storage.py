import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from plexconfigcontrol.plex_storage import discover_plex_storage, StorageDiscoveryError
from plexconfigcontrol.installation_storage import plan_storage, create_storage, manual_path_prompt


class PlexStorageTests(unittest.TestCase):
    def fixture(self, kind='ix_volume', source='/mnt/.ix-apps/app_mounts/plex/config'):
        config={'storage':{'config':{'type':kind,'host_path_config':{'path':source}},
                           'data':{'type':'host_path','host_path_config':{'path':'/mnt/media'}}},'plex':{'claim_token':'SECRET'}}
        mounts=[{'destination':'/config','source':source,'type':'bind'},
                {'destination':'/data','source':'/mnt/media','type':'bind'},
                {'destination':'/config/Library/Application Support/Plex Media Server/Logs','source':'/mnt/logs','type':'volume'}]
        row={'name':'plex','state':'RUNNING','active_workloads':{'volumes':mounts}}
        fs={'fstype':'zfs','source':'tank/plex-config','dest':source}
        api=Mock()
        def call(method,*args):
            if method=='app.config':
                self.assertEqual(args,('plex',));return copy.deepcopy(config)
            if method=='app.query':
                self.assertEqual(args,([['name','=','plex']],{'select':['name','state','active_workloads']}));return copy.deepcopy([row])
            if method=='filesystem.statfs':
                self.assertEqual(args,(source,));return copy.deepcopy(fs)
            self.fail('Unexpected host call: '+method)
        api.call.side_effect=call
        return api,config,row,fs

    def test_ixvolume_is_taken_from_actual_mount_not_hardcoded_pool(self):
        api,_,_,_=self.fixture(source='/mnt/other-apps/plex-config')
        result=discover_plex_storage(api)
        self.assertEqual(result.source,'/mnt/other-apps/plex-config')
        self.assertEqual(result.storage_type,'ix_volume');self.assertTrue(result.dedicated_dataset_root)
        self.assertNotIn('SECRET',repr(result))

    def test_hostpath_and_acl_variant_match_actual_config(self):
        for acl in (False,True):
            api,config,row,fs=self.fixture('host_path','/mnt/tank/My Plex')
            if acl:config['storage']['config']['host_path_config']={'acl_enable':True,'acl':{'path':'/mnt/tank/My Plex'}}
            row['state']='STOPPED'
            self.assertEqual(discover_plex_storage(api).source,'/mnt/tank/My Plex')

    def test_manual_fallback_without_app_config_read_is_verified(self):
        api,config,_,_=self.fixture('unknown','/mnt/tank/plex')
        with self.assertRaises(StorageDiscoveryError):discover_plex_storage(api)
        api.reset_mock()
        result=discover_plex_storage(api,manual_source='/mnt/tank/plex')
        self.assertEqual(result.storage_type,'manual')
        self.assertTrue(all(call.args[0]!='app.config' for call in api.call.call_args_list))
        with self.assertRaisesRegex(StorageDiscoveryError,'SETTINGS_MOUNT_MISMATCH'):
            discover_plex_storage(api,manual_source='/mnt/tank/wrong')

    def test_ambiguous_mount_mismatch_non_zfs_and_missing_mount_rejected(self):
        for scenario in ('duplicate','settings','nonzfs','missing','transition'):
            api,config,row,fs=self.fixture('host_path')
            if scenario=='duplicate':row['active_workloads']['volumes'].append({'destination':'/config','source':'/mnt/other','type':'bind'})
            if scenario=='settings':config['storage']['config']['host_path_config']['path']='/mnt/wrong'
            if scenario=='nonzfs':fs['fstype']='ext4'
            if scenario=='missing':row['active_workloads']['volumes']=[]
            if scenario=='transition':row['state']='DEPLOYING'
            with self.subTest(scenario=scenario),self.assertRaises(StorageDiscoveryError):discover_plex_storage(api)

    def test_path_change_during_detection_is_not_accepted(self):
        api,_,_,_=self.fixture();base=api.call.side_effect;reads=0
        def changing(method,*args):
            nonlocal reads
            value=base(method,*args)
            if method=='filesystem.statfs':
                reads+=1
                if reads==2:value['source']='tank/another'
            return value
        api.call.side_effect=changing
        with self.assertRaisesRegex(StorageDiscoveryError,'PLEX_STORAGE_CHANGED'):discover_plex_storage(api)

    def test_protected_paths_and_traversal_rejected_before_any_probe(self):
        for source in ('/mnt/TrueNAS/TrueNAS/PBS-Data','/mnt/TrueNAS/TrueNAS/PBS-Data/plex','/mnt/tank/../plex','relative'):
            api=Mock()
            with self.subTest(source=source),self.assertRaises(StorageDiscoveryError):discover_plex_storage(api,manual_source=source)
            api.call.assert_not_called()

    def test_shared_dataset_subfolder_is_detected_but_not_approved_for_whole_rollback(self):
        api,_,_,fs=self.fixture('host_path','/mnt/tank/shared/plex');fs['dest']='/mnt/tank/shared'
        detected=discover_plex_storage(api)
        self.assertEqual(detected.relative_path,'plex');self.assertFalse(detected.dedicated_dataset_root)
        with patch('plexconfigcontrol.installation_storage.inspect_destination') as inspect:
            with self.assertRaisesRegex(StorageDiscoveryError,'DEDICATED_PLEX_DATASET_REQUIRED'):
                plan_storage(api,'/mnt/tank/backups')
            inspect.assert_not_called()

    def test_installer_inspects_then_rechecks_before_creating(self):
        api,_,_,fs=self.fixture('host_path','/mnt/tank/plex')
        with patch('plexconfigcontrol.installation_storage.inspect_destination') as inspect,patch('plexconfigcontrol.installation_storage.create_destination') as create:
            plan=plan_storage(api,'/mnt/tank/backups',manual_source='/mnt/tank/plex')
            inspect.assert_called_once();create.assert_not_called()
            fs['source']='tank/replaced'
            with self.assertRaisesRegex(StorageDiscoveryError,'PLEX_STORAGE_CHANGED'):create_storage(api,plan)
            create.assert_not_called()
            fs['source']='tank/plex-config';create_storage(api,plan);create.assert_called_once()

    def test_dedicated_plex_and_backup_storage_can_use_separate_custom_pools(self):
        api, _, _, fs = self.fixture('host_path', '/mnt/MediaPool/Services/PlexData')
        fs['source'] = 'MediaPool/Services/PlexData'
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / 'ArchivePool' / 'Home Backups'
            parent.mkdir(parents=True)
            plan = plan_storage(api, parent, folder_name='Plex Config')
            self.assertEqual(plan.plex.dataset, 'MediaPool/Services/PlexData')
            self.assertEqual(plan.parent, str(parent))
            destination = create_storage(api, plan)
            self.assertEqual(destination.root, parent / 'Plex Config')
            self.assertTrue(destination.logs.is_dir())

    def test_raw_api_errors_do_not_disclose_credentials(self):
        api=Mock();api.call.side_effect=RuntimeError('SECRET from API')
        with self.assertRaises(StorageDiscoveryError) as error:discover_plex_storage(api)
        self.assertEqual(error.exception.code,'PLEX_STORAGE_READ_FAILED');self.assertNotIn('SECRET',str(error.exception))

    def test_manual_entry_remains_available_for_all_detection_failures(self):
        for language in ('en','pl'):
            prompt=manual_path_prompt(StorageDiscoveryError('PLEX_STORAGE_READ_FAILED'),language)
            self.assertTrue(prompt['manual_entry_available'])
            self.assertTrue(prompt['verification_required'])
            self.assertEqual(prompt['field'],'manual_plex_config_path')
