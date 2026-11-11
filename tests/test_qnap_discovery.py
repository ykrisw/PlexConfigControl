import subprocess
import unittest
from types import SimpleNamespace

from plexconfigcontrol.qnap_discovery import discover_qnap_plex, storage_for_path, QnapDiscoveryError


INSTALL = '/share/ZFS530_DATA/.qpkg/PlexMediaServer'
DATA = INSTALL+'/Library/Plex Media Server'
LISTING = 'zpool1/zfs530\t/share/ZFS530_DATA\nzpool1/zfs530@:init:\t-'


class QnapDiscoveryTests(unittest.TestCase):
    def test_shared_qnap_filesystem_is_not_a_dedicated_plex_dataset(self):
        commands = []
        def run(argv, **options):
            commands.append(argv)
            value = {'Install_Path': INSTALL, 'Version': '1.43.5', 'Enable': 'TRUE'}[argv[2]] if argv[0].endswith('getcfg') else LISTING
            return SimpleNamespace(returncode=0, stdout=value)
        found = discover_qnap_plex(runner=run, resolve=lambda path: path,
            is_directory=lambda path: path==DATA)
        self.assertEqual(found.dataset, 'zpool1/zfs530')
        self.assertEqual(found.relative_path, '.qpkg/PlexMediaServer/Library/Plex Media Server')
        self.assertFalse(found.dedicated_dataset_root)
        self.assertTrue(found.package_enabled)
        self.assertTrue(all(argv[0] == '/sbin/getcfg' or argv[:5] == ['/sbin/zfs', 'list', '-H', '-t', 'filesystem'] for argv in commands))

    def test_nested_filesystem_wins_over_its_parent(self):
        listing = LISTING+'\nzpool1/zfs530/plex\t'+DATA
        self.assertEqual(storage_for_path(DATA, listing), ('zpool1/zfs530/plex', DATA, '.'))

    def test_equal_depth_mount_ambiguity_is_rejected(self):
        with self.assertRaisesRegex(QnapDiscoveryError, 'AMBIGUOUS'):
            storage_for_path(DATA, LISTING+'\nother/volume\t/share/ZFS530_DATA')

    def test_prefix_collision_does_not_match_another_mount(self):
        with self.assertRaisesRegex(QnapDiscoveryError, 'NOT_FOUND'):
            storage_for_path(DATA, 'other/volume\t/share/ZFS530_DATA-other')

    def test_snapshot_records_are_never_selected_as_filesystems(self):
        with self.assertRaisesRegex(QnapDiscoveryError, 'NOT_FOUND'):
            storage_for_path(DATA, 'zpool1/zfs530@:init:\t/share/ZFS530_DATA')

    def test_permission_failure_does_not_leak_stderr(self):
        def run(argv, **options):
            return SimpleNamespace(returncode=1, stdout='', stderr='private data')
        with self.assertRaisesRegex(QnapDiscoveryError, '^QNAP_DISCOVERY_ACCESS_REQUIRED$'):
            discover_qnap_plex(runner=run)

    def test_data_symlink_outside_package_is_rejected(self):
        def run(argv, **options):
            return SimpleNamespace(returncode=0, stdout={'Install_Path':INSTALL,
                'Version':'1.43.5','Enable':'TRUE'}[argv[2]])
        with self.assertRaisesRegex(QnapDiscoveryError, 'OUTSIDE_PACKAGE'):
            discover_qnap_plex(runner=run, resolve=lambda path: path if path==INSTALL else '/share/Other/private',
                is_directory=lambda path: path==DATA)
