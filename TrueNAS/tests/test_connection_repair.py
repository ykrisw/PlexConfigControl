import copy
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from plexconfigcontrol import connection_repair as repair
from test_tls_recovery import certificate,pem


class ConnectionRepair(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.folder=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.ca=self.folder/'truenas-ca.pem';self.old=pem(certificate()[1]);self.new=pem(certificate()[1]);self.ca.write_text(self.old)
        self.key=self.folder/'truenas-key';self.key.write_text('fixture-only-key')
        self.archive=self.folder/'backup.tar.gz';self.archive.write_bytes(b'keep-user-backup')
        self.compose={'services':{'worker':{'command':['--truenas-url','wss://127.0.0.1:443/api/current'],
            'volumes':[{'target':'/run/pcc-secrets/truenas-ca','source':str(self.ca)}]}}}
        self.api=Mock();self.api.call.return_value=self.compose
        self.client=Mock();self.client.call.return_value={'ui_httpsport':443}
        self.verify=Mock(return_value=self.new)
        self.stack.enter_context(patch.object(repair.os,'geteuid',return_value=0))
        self.stack.enter_context(patch.object(repair,'_details',return_value=(self.folder/'update-recovery.json',SimpleNamespace(host_ip='127.0.0.1',host_port=8443))))
        self.stack.enter_context(patch.object(repair,'_installed',side_effect=['RUNNING','STOPPED']))
        self.stop=self.stack.enter_context(patch.object(repair,'_stop'))
        self.ready=self.stack.enter_context(patch.object(repair,'_ready'))
        self.probe=self.stack.enter_context(patch.object(repair,'_verify_worker_api'))
        self.stack.enter_context(patch.object(repair,'_read_ca',side_effect=lambda path:path.read_text()))
        self.stack.enter_context(patch('builtins.input',return_value='tak'))

    def test_repair_changes_only_public_trust_and_restarts_app(self):
        previous=copy.deepcopy(self.compose)
        repair._repair_connection(self.api,self.client,self.verify)
        self.assertEqual(self.ca.read_text(),self.new)
        self.assertEqual(self.key.read_text(),'fixture-only-key')
        self.assertEqual(self.archive.read_bytes(),b'keep-user-backup')
        self.assertEqual(self.compose,previous)
        self.stop.assert_called_once_with(self.api,self.compose,trust_only=True)
        self.api.start.assert_called_once();self.ready.assert_called_once()
        self.assertFalse((self.folder/'connection-repair.json').exists())

    def test_failed_start_retains_recovery_evidence_without_touching_credentials(self):
        self.api.start.side_effect=RuntimeError('fixture interrupted start')
        with self.assertRaisesRegex(Exception,'record is retained'):
            repair._repair_connection(self.api,self.client,self.verify)
        self.assertTrue((self.folder/'connection-repair.json').exists())
        self.assertEqual(self.key.read_text(),'fixture-only-key')
        self.assertEqual(self.archive.read_bytes(),b'keep-user-backup')

    def test_active_operation_refusal_makes_no_trust_or_app_change(self):
        self.stop.side_effect=RuntimeError('operation active')
        with self.assertRaises(RuntimeError):repair._repair_connection(self.api,self.client,self.verify)
        self.assertEqual(self.ca.read_text(),self.old)
        self.api.start.assert_not_called()
        self.assertFalse((self.folder/'connection-repair.json').exists())

    def test_unverified_ca_never_reaches_stop_or_write(self):
        self.verify.side_effect=RuntimeError('certificate verification failed')
        with self.assertRaises(RuntimeError):repair._repair_connection(self.api,self.client,self.verify)
        self.assertEqual(self.ca.read_text(),self.old);self.stop.assert_not_called()

    def test_local_health_is_not_mistaken_for_a_verified_api_connection(self):
        self.probe.side_effect=RuntimeError('API TLS is still unavailable')
        with self.assertRaisesRegex(Exception,'record is retained'):
            repair._repair_connection(self.api,self.client,self.verify)
        self.assertTrue((self.folder/'connection-repair.json').exists())
