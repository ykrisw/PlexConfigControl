import tempfile
import unittest
from plexconfigcontrol.settings import Settings

class SettingsTests(unittest.TestCase):
    def test_defaults_and_persistent_manual_theme(self):
        with tempfile.TemporaryDirectory() as d:
            settings=Settings(d)
            self.assertEqual(settings.read()['theme'],'System')
            settings.update(theme='Dark')
            self.assertEqual(Settings(d).read()['theme'],'Dark')
            settings.update(theme='System')
            self.assertEqual(Settings(d).read()['theme'],'System')

    def test_invalid_batch_does_not_partially_change_settings(self):
        with tempfile.TemporaryDirectory() as d:
            settings=Settings(d)
            with self.assertRaises(ValueError): settings.update(theme='Dark',language='invalid')
            self.assertEqual(settings.read()['theme'],'System')
            with self.assertRaises(ValueError): settings.update(timezone='not/a/timezone')
            self.assertEqual(settings.read()['timezone'],'Europe/London')
            with self.assertRaises(ValueError): settings.update(password='secret')
