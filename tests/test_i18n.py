import tempfile
import unittest
from datetime import datetime, timezone
from plexconfigcontrol.i18n import CATALOG, translate
from plexconfigcontrol.settings import Settings
from plexconfigcontrol.archives import archive_name

class TranslationTests(unittest.TestCase):
    def test_catalogs_cover_same_keys(self):
        self.assertEqual(set(CATALOG['en']),set(CATALOG['pl']))
        self.assertTrue(all(CATALOG['pl'].values()))
        self.assertEqual(translate('change_password','pl'),'Zmień hasło')
        self.assertIn('RESTORE',translate('type_restore','pl'))
    def test_polish_persists_without_renaming_archives(self):
        with tempfile.TemporaryDirectory() as d:
            settings=Settings(d)
            self.assertEqual(settings.read()['language'],'en')
            settings.update(language='pl')
            self.assertEqual(Settings(d).read()['language'],'pl')
            self.assertEqual(archive_name(datetime(2026,11,3,4,15,35,tzinfo=timezone.utc)),
                             'TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz')
