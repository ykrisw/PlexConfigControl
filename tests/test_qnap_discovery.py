import subprocess
import unittest
from types import SimpleNamespace

from plexconfigcontrol.qnap_discovery import discover_qnap_plex, storage_for_path, QnapDiscoveryError


INSTALL = '/share/ZFS100_DATA/.qpkg/PlexMediaServer'
DATA = INSTALL+'/Library/Plex Media Server'
LISTING = 'zpool9/zfs100\t/share/ZFS100_DATA\nzpool9/zfs100@:init:\t-'


class QnapDiscoveryTests(unittest.TestCase):
    def test_shared_qnap_filesystem_is_not_a_dedicated_plex_dataset(self):
        commands = []
        def run(argv, **options):
            commands.append(argv)
            if argv[0] == '/sbin/getcfg':
                value = {'Install_Path': INSTALL, 'Version': '1.0.0', 'Enable': 'TRUE'}[argv[2]]
            elif argv[0] == '/sbin/zfs':
                value = LISTING
            elif argv == ['/sbin/snapshot_util', 'get_volume_id', '/share/ZFS100_DATA']:
                value = '7\n'
            else:
                self.fail('Unexpected discovery command: '+repr(argv))
            return SimpleNamespace(returncode=0, stdout=value)
        found = discover_qnap_plex(runner=run, resolve=lambda path: path,
            is_directory=lambda path: path==DATA)
        self.assertEqual(found.dataset, 'zpool9/zfs100')
        self.assertEqual(found.volume_id, 7)
        self.assertEqual(found.relative_path, '.qpkg/PlexMediaServer/Library/Plex Media Server')
        self.assertFalse(found.dedicated_dataset_root)
        self.assertTrue(found.package_enabled)
        self.assertTrue(all(argv[0] == '/sbin/getcfg'
            or argv[:5] == ['/sbin/zfs', 'list', '-H', '-t', 'filesystem']
            or argv == ['/sbin/snapshot_util', 'get_volume_id', '/share/ZFS100_DATA']
            for argv in commands))

    def test_nested_filesystem_wins_over_its_parent(self):
        listing = LISTING+'\nzpool9/zfs100/plex\t'+DATA
        self.assertEqual(storage_for_path(DATA, listing), ('zpool9/zfs100/plex', DATA, '.'))

    def test_equal_depth_mount_ambiguity_is_rejected(self):
        with self.assertRaisesRegex(QnapDiscoveryError, 'AMBIGUOUS'):
            storage_for_path(DATA, LISTING+'\nother/volume\t/share/ZFS100_DATA')

    def test_prefix_collision_does_not_match_another_mount(self):
        with self.assertRaisesRegex(QnapDiscoveryError, 'NOT_FOUND'):
            storage_for_path(DATA, 'other/volume\t/share/ZFS100_DATA-other')

    def test_snapshot_records_are_never_selected_as_filesystems(self):
        with self.assertRaisesRegex(QnapDiscoveryError, 'NOT_FOUND'):
            storage_for_path(DATA, 'zpool9/zfs100@:init:\t/share/ZFS100_DATA')

    def test_permission_failure_does_not_leak_stderr(self):
        def run(argv, **options):
            return SimpleNamespace(returncode=1, stdout='', stderr='private data')
        with self.assertRaisesRegex(QnapDiscoveryError, '^QNAP_DISCOVERY_ACCESS_REQUIRED$'):
            discover_qnap_plex(runner=run)

    def test_data_symlink_outside_package_is_rejected(self):
        def run(argv, **options):
            return SimpleNamespace(returncode=0, stdout={'Install_Path':INSTALL,
                'Version':'1.0.0','Enable':'TRUE'}[argv[2]])
        with self.assertRaisesRegex(QnapDiscoveryError, 'OUTSIDE_PACKAGE'):
            discover_qnap_plex(runner=run, resolve=lambda path: path if path==INSTALL else '/share/Other/private',
                is_directory=lambda path: path==DATA)

    def test_volume_lookup_rejects_invalid_output_without_fallback(self):
        for output in ('', '0', '-1', '7\n8', 'Volume_ID:7', '7; command', '99999999999'):
            def run(argv, **options):
                if argv[0] == '/sbin/getcfg':
                    value = {'Install_Path':INSTALL, 'Version':'1.0.0', 'Enable':'TRUE'}[argv[2]]
                elif argv[0] == '/sbin/zfs':
                    value = LISTING
                else:
                    value = output
                return SimpleNamespace(returncode=0, stdout=value)
            with self.subTest(output=output), self.assertRaisesRegex(QnapDiscoveryError, 'INVALID_QNAP_VOLUME_ID'):
                discover_qnap_plex(runner=run, resolve=lambda path:path,
                    is_directory=lambda path:path==DATA)

    def test_native_volume_failure_is_reported_without_guessing(self):
        def run(argv, **options):
            if argv[0] == '/sbin/getcfg':
                value = {'Install_Path':INSTALL, 'Version':'1.0.0', 'Enable':'TRUE'}[argv[2]]
            elif argv[0] == '/sbin/zfs':
                value = LISTING
            else:
                return SimpleNamespace(returncode=1, stdout='7', stderr='private details')
            return SimpleNamespace(returncode=0, stdout=value)
        with self.assertRaisesRegex(QnapDiscoveryError, '^QNAP_DISCOVERY_ACCESS_REQUIRED$'):
            discover_qnap_plex(runner=run, resolve=lambda path:path,
                is_directory=lambda path:path==DATA)
