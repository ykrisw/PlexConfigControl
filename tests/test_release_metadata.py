"""Guard against filename-only releases with stale application/package versions."""
import importlib.util
from pathlib import Path
import re
import tempfile
import tomllib
import unittest
from xml.etree import ElementTree as ET
from plexconfigcontrol import __version__

ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_application_panel_and_qnap_control_metadata_match_release(self):
        self.assertEqual(__version__, '1.6')
        self.assertEqual(tomllib.loads((ROOT/'pyproject.toml').read_text(encoding="utf-8"))['project']['version'], __version__)
        settings = (ROOT/'plexconfigcontrol/static/settings-view.mjs').read_text(encoding="utf-8")
        self.assertIn("'[data-version]':'1.6'", settings)
        cfg = (ROOT/'deploy/qnap/qpkg/qpkg.cfg').read_text(encoding="utf-8")
        self.assertEqual(re.search(r'^QPKG_VER="([^"]+)"',cfg,re.M)[1], __version__)
        self.assertEqual(re.search(r'^QPKG_AUTHOR="([^"]+)"',cfg,re.M)[1], 'Krzysztof Wojciechowski')

    def test_app_center_feed_preserves_identity_version_author_and_description(self):
        spec = importlib.util.spec_from_file_location('make_repository', ROOT/'deploy/qnap/make_repository.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            package = folder/'PlexConfigControlQuTShero_1.6.qpkg'
            package.write_bytes(b'feed-test-fixture')
            for language in ('en','pl'):
                path = folder/(language+'.xml')
                module.make(package,path,language)
                item = ET.parse(path).getroot().find('item')
                self.assertEqual(item.findtext('internalName'), 'PCC')
                self.assertEqual(item.findtext('version'), __version__)
                self.assertEqual(item.findtext('developer'), 'Krzysztof Wojciechowski')
                self.assertEqual(item.findtext('description'), module.DESCRIPTION[language])
                self.assertTrue(item.findtext('platform/location').endswith('/v1.6/'+package.name))
