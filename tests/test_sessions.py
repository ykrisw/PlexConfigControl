import tempfile
import unittest
from plexconfigcontrol.sessions import Sessions

class SessionTests(unittest.TestCase):
    def test_restart_keeps_session_logout_invalidates_it(self):
        with tempfile.TemporaryDirectory() as d:
            sessions=Sessions(d); token,csrf=sessions.create()
            reopened=Sessions(d)
            self.assertTrue(reopened.authenticated(token))
            self.assertTrue(reopened.check_csrf(token,csrf))
            reopened.logout(token)
            self.assertFalse(sessions.authenticated(token))
            self.assertFalse(sessions.check_csrf(token,csrf))

    def test_tokens_are_hashed_and_csrf_is_session_specific(self):
        with tempfile.TemporaryDirectory() as d:
            sessions=Sessions(d); first,csrf=sessions.create(); second,other=sessions.create()
            self.assertNotIn(first.encode(),sessions.path.read_bytes())
            self.assertFalse(sessions.check_csrf(second,csrf))
            self.assertFalse(sessions.authenticated(None))
            sessions.revoke_all()
            self.assertFalse(sessions.authenticated(first))
            self.assertFalse(sessions.authenticated(second))
