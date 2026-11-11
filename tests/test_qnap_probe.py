import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


PROBE = Path(__file__).resolve().parents[1]/'deploy/qnap/PCC_QNAP_API_Probe.py'


class QnapProbeTests(unittest.TestCase):
    def namespace(self, fail_counter=False):
        namespace = {'__name__': 'pcc_probe_definitions'}
        exec(compile(PROBE.read_bytes(), str(PROBE), 'exec'), namespace)
        calls = []
        api_error = namespace['QnapApiError']
        class FakeApi:
            def __init__(self, *args, **options):
                calls.append('construct')
            def probe(self):
                calls.append('probe')
                return {'root': 'QDocRoot'}
            def login(self, username, password):
                self.username, self.password = username, password
                calls.append('login')
            def snapshot_count(self, volume):
                calls.append('count')
                if fail_counter:
                    raise api_error('QNAP_SNAPSHOT_SCHEMA_UNVERIFIED')
                return 0
            def snapshots(self, volume):
                calls.append('list')
                return []
            def forget_session(self):
                calls.append('forget')
        namespace.update(discover_qnap_plex=lambda: SimpleNamespace(volume_id=7),
            local_certificate_context=lambda pem: (None, 'test-pin'), QnapLocalReadOnlyApi=FakeApi)
        return namespace, calls

    def run_probe(self, namespace):
        output = io.StringIO()
        with patch.dict(os.environ, {'SUDO_USER':'test-account'}), \
                patch('builtins.input', return_value=''), \
                patch('getpass.getpass', return_value='test-password-never-print'), \
                patch('pathlib.Path.read_text', return_value='test-public-certificate'), \
                contextlib.redirect_stdout(output):
            result = namespace['probe_main']()
        self.assertNotIn('test-password-never-print', output.getvalue())
        return result, output.getvalue()

    def test_count_and_list_probe_is_read_only_and_forgets_session(self):
        namespace, calls = self.namespace()
        result, output = self.run_probe(namespace)
        self.assertEqual(result, 0)
        self.assertEqual(calls, ['construct', 'probe', 'login', 'count', 'list', 'forget'])
        self.assertIn('Zgodność licznika i listy: OK', output)

    def test_unknown_counter_fails_without_proceeding_and_forgets_session(self):
        namespace, calls = self.namespace(fail_counter=True)
        result, output = self.run_probe(namespace)
        self.assertEqual(result, 1)
        self.assertEqual(calls, ['construct', 'probe', 'login', 'count', 'forget'])
        self.assertIn('QNAP_SNAPSHOT_SCHEMA_UNVERIFIED', output)

    def test_bundled_probe_loads_with_standard_library_only(self):
        code = ('from pathlib import Path; import sys; ns={"__name__":"probe_definitions"}; '
                'exec(compile(Path(sys.argv[1]).read_bytes(),"probe","exec"),ns); '
                'assert callable(ns["discover_qnap_plex"]); '
                'assert callable(ns["QnapLocalReadOnlyApi"]); '
                'assert callable(ns["probe_main"])')
        subprocess.run([sys.executable, '-I', '-S', '-c', code, str(PROBE)], check=True)
