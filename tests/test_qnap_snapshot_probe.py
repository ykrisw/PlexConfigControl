import unittest
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from plexconfigcontrol.qnap_api import QnapApiError
from plexconfigcontrol.qnap_snapshot_probe import OwnedSnapshotProbe, SnapshotProbeError, snapshot_mount_source


class FakeApi:
    _session = 'test_session_123'

    def __init__(self, mode='ok'):
        self.rows = [{'id': '10', 'name': 'existing'}]
        self.storage = {'pool/data@existing'}
        self.mode, self.changes = mode, []

    def snapshots(self, volume):
        return [dict(row) for row in self.rows]

    def snapshot_count(self, volume):
        return len(self.rows)

    def _exchange_xml(self, method, path, fields):
        self.changes.append(dict(fields))
        root = ET.fromstring('<QDocRoot><authPassed>1</authPassed><result>0</result></QDocRoot>')
        if fields['func'] == 'create_snapshot':
            if self.mode == 'lost-no-creation':
                raise QnapApiError('QNAP_LOCAL_API_UNAVAILABLE')
            self.rows.append({'id': '20', 'name': fields['snapshot_name']})
            self.storage.add('pool/data@fresh')
            if self.mode == 'lost-create':
                raise QnapApiError('QNAP_LOCAL_API_UNAVAILABLE')
            info = ET.SubElement(root, 'SnapshotInfo')
            ET.SubElement(info, 'snapshot_id').text = '10' if self.mode == 'bad-id' else '20'
            ET.SubElement(info, 'snapshot_name').text = fields['snapshot_name']
        else:
            if fields['snapshotID'] != '20':
                raise AssertionError('Attempt to delete an existing snapshot')
            self.rows = self.rows[:1]
            if self.mode != 'storage-remains':
                self.storage.remove('pool/data@fresh')
            if self.mode == 'lost-delete':
                raise QnapApiError('QNAP_LOCAL_API_UNAVAILABLE')
        return root


class SnapshotProbeTests(unittest.TestCase):
    def run_case(self, mode='ok', inspect=None):
        api = FakeApi(mode)
        probe = OwnedSnapshotProbe(api, SimpleNamespace(volume_id=7, dataset='pool/data'),
            read_storage=lambda: set(api.storage),
            inspect_data=inspect or (lambda identifier, baseline: 'pool/data@fresh'),
            pause=lambda seconds: None)
        return api, probe, probe.run()

    def test_complete_lifecycle_preserves_existing_snapshot(self):
        api, probe, result = self.run_case()
        self.assertTrue(result['created'] and result['readable'] and result['cleanup_confirmed'])
        self.assertIsNone(result['error'])
        self.assertEqual(api.storage, {'pool/data@existing'})
        self.assertEqual([x['func'] for x in api.changes], ['create_snapshot', 'del_snapshots'])
        self.assertEqual(api.changes[0]['expire_min'], '15')

    def test_lost_create_reply_recovers_nonce_and_cleans_without_retry(self):
        api, probe, result = self.run_case('lost-create')
        self.assertTrue(result['cleanup_confirmed'])
        self.assertIsNotNone(result['error'])
        self.assertEqual(len(api.changes), 2)

    def test_missing_create_identity_never_claims_cleanup(self):
        api, probe, result = self.run_case('lost-no-creation')
        self.assertFalse(result['cleanup_confirmed'])
        self.assertEqual(len(api.changes), 1)

    def test_invalid_create_echo_never_deletes_baseline_id(self):
        api, probe, result = self.run_case('bad-id')
        self.assertEqual(result['error'], 'PROBE_CREATE_IDENTITY_MISMATCH')
        self.assertTrue(result['cleanup_confirmed'])
        self.assertEqual(api.changes[-1]['snapshotID'], '20')

    def test_read_failure_still_cleans(self):
        def fail(*args):
            raise SnapshotProbeError('PROBE_READ_TEST_FAILED')
        api, probe, result = self.run_case(inspect=fail)
        self.assertFalse(result['readable'])
        self.assertTrue(result['cleanup_confirmed'])

    def test_api_absence_alone_is_not_cleanup(self):
        api, probe, result = self.run_case('storage-remains')
        self.assertFalse(result['cleanup_confirmed'])
        self.assertEqual(result['cleanup_error'], 'PROBE_CONFIRMATION_TIMEOUT')
        self.assertEqual(len(api.changes), 2)

    def test_lost_delete_reply_observes_cleanup_without_second_delete(self):
        api, probe, result = self.run_case('lost-delete')
        self.assertTrue(result['cleanup_confirmed'])
        self.assertEqual(len(api.changes), 2)

    def test_renamed_identity_blocks_delete(self):
        api = FakeApi()
        probe = OwnedSnapshotProbe(api, SimpleNamespace(volume_id=7, dataset='pool/data'))
        probe.identifier = '10'
        with self.assertRaisesRegex(SnapshotProbeError, 'IDENTITY_CHANGED'):
            probe._change('del_snapshots')
        self.assertEqual(api.changes, [])

    def test_standalone_bundle_requires_explicit_opt_in(self):
        bundle = Path(__file__).resolve().parents[1]/"deploy/qnap/PCC_QNAP_Snapshot_Probe.py"
        result = subprocess.run([sys.executable, "-I", "-S", str(bundle)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--test-snapshot", result.stdout)
        self.assertNotIn("Użytkownik", result.stdout)

    def test_mount_must_be_exact_readonly_snapshot(self):
        valid = '2 1 0:2 / /preview ro,relatime - zfs pool/data@fresh ro'
        self.assertEqual(snapshot_mount_source('/preview/Plex', valid, 'pool/data'), 'pool/data@fresh')
        for invalid in (valid.replace('ro,relatime', 'rw,relatime'),
                        valid.replace('@fresh', ''), valid.replace('pool/data@', 'pool/other@'),
                        valid+'\n'+valid):
            with self.assertRaises(SnapshotProbeError):
                snapshot_mount_source('/preview/Plex', invalid, 'pool/data')


if __name__ == '__main__':
    unittest.main()
