import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from retail_opera import opera_binary


class RetailOperaTests(unittest.TestCase):
    def test_missing_opera_never_substitutes_chrome(self):
        with patch('retail_opera.platform.system',return_value='Linux'),patch('retail_opera.shutil.which',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'refusing to substitute'):
                opera_binary()

    def test_windows_uses_versioned_executable_not_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'Programs'/'Opera';root.mkdir(parents=True)
            (root/'launcher.exe').touch()
            for version in ('9.0.1','10.0.1'):
                (root/version).mkdir();(root/version/'opera.exe').touch()
            with patch('retail_opera.platform.system',return_value='Windows'),patch.dict(os.environ,{'LOCALAPPDATA':tmp},clear=True):
                self.assertEqual(opera_binary(),str(root/'10.0.1'/'opera.exe'))
