import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from plexconfigcontrol.naming import Naming, InvalidNaming, ARCHIVE_NAME, save_naming, load_naming
from plexconfigcontrol.archives import archive_name
from plexconfigcontrol.archive_store import ArchiveStore
from plexconfigcontrol.storage import create_destination, verify_destination, RenameRequired
from plexconfigcontrol.installation_flow import InstallationStorageFlow
from plexconfigcontrol.installation_storage import plan_storage
from plexconfigcontrol.plex_storage import PlexStorage


class NamingTests(unittest.TestCase):
    def test_defaults_and_custom_prefix_always_keep_london_timestamp_and_extension(self):
        instant=datetime(2026,7,3,4,15,35,tzinfo=timezone.utc)
        self.assertEqual(archive_name(instant),'PlexConfig_2026.07.03_05.15.35.tar.gz')
        self.assertEqual(archive_name(instant,prefix='Dupa'),'Dupa_2026.07.03_05.15.35.tar.gz')
        self.assertEqual(Naming.from_input('', ''),Naming('Plex Backup','PlexConfig'))
        with self.assertRaises(ValueError):archive_name(datetime(2026,7,3))

    def test_custom_folder_fixed_logs_and_identity_rechecks(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination=create_destination(tmp,folder_name='Moje kopie Plex')
            self.assertEqual(destination.root,Path(tmp)/'Moje kopie Plex')
            self.assertEqual(destination.logs,destination.root/'Logs')
            self.assertTrue(verify_destination(destination))
            with self.assertRaises(RenameRequired):create_destination(tmp,folder_name='Moje kopie Plex')
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),['Moje kopie Plex'])

    def test_prefixes_and_folder_names_cannot_escape_or_change_extension(self):
        for prefix in ('../bad','a/b','a\\b','Name.tar.gz','%Y',' bad','a'*65,''):
            with self.subTest(prefix=prefix),self.assertRaises(InvalidNaming):Naming(archive_prefix=prefix)
        for folder in ('../bad','/mnt/elsewhere','a/b','a\\b','CON','NUL.txt','name.','name ',''):
            with tempfile.TemporaryDirectory() as tmp:
                with self.subTest(folder=folder),self.assertRaises(InvalidNaming):create_destination(tmp,folder_name=folder)
                self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_listing_accepts_custom_default_and_old_prefixes_without_renaming(self):
        names=['Dupa_2026.11.04_10.20.30.tar.gz','PlexConfig_2026.11.04_10.20.30.tar.gz',
               'TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in names:(root/name).write_bytes(b'archive fixture')
            (root/'bad.tar.gz').write_bytes(b'ignored')
            self.assertEqual({item.name for item in ArchiveStore(root,root/'state').list()},set(names))
            for name in names:self.assertEqual((root/name).read_bytes(),b'archive fixture')

    def test_installation_plan_binds_both_names_and_existing_custom_folder(self):
        source=PlexStorage('host_path','/mnt/tank/plex','tank/plex','/mnt/tank/plex','.')
        with tempfile.TemporaryDirectory() as tmp,patch('plexconfigcontrol.installation_storage.discover_plex_storage',return_value=source):
            plan=plan_storage(Mock(),tmp,folder_name='Moje kopie',archive_prefix='Dupa')
            self.assertEqual(plan.naming,Naming('Moje kopie','Dupa'))
            flow=InstallationStorageFlow(Mock())
            view=flow.check(tmp,folder_name='Moje kopie',archive_prefix='Dupa')
            self.assertEqual(view['storage']['output'],str(Path(tmp)/'Moje kopie'))
            self.assertEqual(view['storage']['archive_prefix'],'Dupa')
            (Path(tmp)/'Moje kopie').mkdir()
            self.assertEqual(flow.check(tmp,folder_name='Moje kopie',archive_prefix='Dupa')['phase'],'RENAME_REQUIRED')

    def test_invalid_install_names_do_not_query_host_or_create(self):
        api=Mock();flow=InstallationStorageFlow(api,'pl')
        result=flow.check('/mnt/backups',archive_prefix='../bad')
        self.assertEqual(result['error']['code'],'INVALID_NAMING');api.call.assert_not_called()

    def test_private_names_survive_restart_and_cannot_be_silently_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            chosen=Naming('Kopie Plex','Dupa')
            save_naming(tmp,chosen);save_naming(tmp,chosen)
            self.assertEqual(load_naming(tmp),chosen)
            self.assertEqual((Path(tmp)/'output-naming.json').stat().st_mode&0o077,0)
            with self.assertRaises(InvalidNaming):save_naming(tmp,Naming())
            self.assertEqual(load_naming(tmp),chosen)
            (Path(tmp)/'output-naming.json').write_text('not JSON')
            with self.assertRaises(InvalidNaming):load_naming(tmp)

    def test_manual_location_on_either_pool_is_honored_without_extra_folders(self):
        source=PlexStorage('host_path','/mnt/apps/plex','apps/plex','/mnt/apps/plex','.')
        for pool in ('Pool_A','Pool_B'):
            with self.subTest(pool=pool),tempfile.TemporaryDirectory() as tmp,patch('plexconfigcontrol.installation_storage.discover_plex_storage',return_value=source):
                root=Path(tmp);parent=root/pool/'dataset';parent.mkdir(parents=True)
                state=root/'private-state';state.mkdir()
                flow=InstallationStorageFlow(Mock(),state_directory=state)
                ready=flow.check(str(parent),folder_name='Moje kopie',archive_prefix='Dupa')
                result=flow.create(ready['revision'],confirmed=True)
                self.assertEqual(result['phase'],'COMPLETE')
                self.assertTrue((parent/'Moje kopie'/'Logs').is_dir())
                self.assertEqual(load_naming(state),Naming('Moje kopie','Dupa'))
                self.assertEqual([p.name for p in (parent/'Moje kopie').iterdir()],['Logs'])
