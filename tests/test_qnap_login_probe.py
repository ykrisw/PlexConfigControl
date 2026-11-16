import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


BUNDLE = Path(__file__).resolve().parents[1]/'deploy/qnap/PCC_QNAP_Snapshot_Probe.py'


class LoginProbeTests(unittest.TestCase):
    def exercise(self, failed):
        namespace = {'__name__': 'probe_definitions'}
        exec(compile(BUNDLE.read_bytes(), 'probe', 'exec'), namespace)
        calls = []
        class Api:
            last_login_diagnostics = {'fields': ['authPassed', 'errorValue'],
                'session_present': False, 'session_format_valid': False,
                'authPassed': '0', 'errorValue': '-5'}
            def __init__(self, *args, **kwargs):
                pass
            def probe(self):
                return {'root': 'QDocRoot'}
            def login(self, user, password, **kwargs):
                calls.append('login')
                if failed:
                    raise namespace['QnapApiError']('QNAP_AUTHENTICATION_FAILED')
            def forget_session(self):
                calls.append('forget')
        def forbidden(*args, **kwargs):
            self.fail('Login-only mode must not instantiate snapshot execution')
        namespace.update(QnapLocalReadOnlyApi=Api, OwnedSnapshotProbe=forbidden,
            discover_qnap_plex=lambda: SimpleNamespace(volume_id=7),
            local_certificate_context=lambda pem: (None, 'test-pin'),
            secure_terminal_password=lambda prompt: 'never-print-test-password')
        output = io.StringIO()
        with patch('sys.argv', ['probe', '--test-login']), patch('builtins.input', return_value='test-user'), \
                patch('pathlib.Path.read_text', return_value='test-cert'), contextlib.redirect_stdout(output):
            code = namespace['snapshot_probe_main']()
        self.assertEqual(calls, ['login', 'forget'])
        self.assertNotIn('never-print-test-password', output.getvalue())
        return code, output.getvalue()

    def test_successful_login_only_never_creates_snapshot(self):
        code, text = self.exercise(False)
        self.assertEqual(code, 0)
        self.assertIn('Logowanie: OK', text)

    def test_failed_login_only_reports_sanitized_reason_without_snapshot(self):
        code, text = self.exercise(True)
        self.assertEqual(code, 1)
        self.assertIn('Kod errorValue: -5', text)
