import tempfile
import unittest
from unittest.mock import patch
from plexconfigcontrol.auth import Account

class AuthTests(unittest.TestCase):
    @patch('plexconfigcontrol.auth.ITERATIONS', 1000)
    def test_escalation_survives_restart_and_success_resets(self):
        with tempfile.TemporaryDirectory() as directory:
            account=Account(directory); account.initialize('correct')
            now=1000
            for attempts, delay in ((5,300),(5,900),(2,900),(1,900),(1,900)):
                for _ in range(attempts):
                    result=account.login('wrong',now)
                self.assertEqual(result['blocked_until'],now+delay)
                account=Account(directory)
                self.assertFalse(account.login('correct',now+1)['authenticated'])
                now+=delay+1
            self.assertTrue(account.login('correct',now)['authenticated'])
            self.assertEqual(account.login('wrong',now)['remaining'],4)

    @patch('plexconfigcontrol.auth.ITERATIONS', 1000)
    def test_change_password(self):
        with tempfile.TemporaryDirectory() as directory:
            account=Account(directory); account.initialize('old')
            self.assertFalse(account.change_password('wrong','new'))
            self.assertTrue(account.change_password('old','new'))
            self.assertFalse(account.login('old')['authenticated'])
            self.assertTrue(account.login('new')['authenticated'])
            self.assertNotIn(b'new',account.path.read_bytes())
