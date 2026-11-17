import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import yaml
from plexconfigcontrol import app_branding


class BrandingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'metadata.yaml'
        self.original = {'custom_app': True, 'version': '1.0.0',
                         'metadata': {'icon': 'old', 'name': 'ix-app'}, 'portals': {'Web': 'unchanged'}}
        self.path.write_text(yaml.safe_dump(self.original))
        self.path.chmod(0o600)
        self.patch = patch.object(app_branding, 'METADATA', self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_only_icon_changes_and_mode_remains_private(self):
        regenerate = Mock()
        app_branding.install_icon(regenerate)
        after = yaml.safe_load(self.path.read_text())
        self.assertTrue(after['metadata']['icon'].startswith('data:image/svg+xml;base64,'))
        after['metadata']['icon'] = 'old'
        self.assertEqual(after, self.original)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        regenerate.assert_called_once()

    def test_failed_regeneration_restores_exact_previous_bytes(self):
        before = self.path.read_bytes()
        with self.assertRaises(RuntimeError):
            app_branding.install_icon(Mock(side_effect=RuntimeError('unavailable')))
        self.assertEqual(self.path.read_bytes(), before)

    def test_symlink_is_rejected_without_touching_target(self):
        target = self.path.with_name('other-app.yaml')
        self.path.rename(target)
        self.path.symlink_to(target)
        before = target.read_bytes()
        with self.assertRaises(ValueError):
            app_branding.install_icon(Mock())
        self.assertEqual(target.read_bytes(), before)
