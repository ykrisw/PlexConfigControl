import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('maintenance_publish',Path(__file__).resolve().parents[1]/'deploy/publish_release.py')
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)

class MaintenancePublication(unittest.TestCase):
    def test_publish_verifies_download_and_never_changes_the_16_release(self):
        content=b'full-verified-maintenance-package';calls=[]
        def gh(*args):
            calls.append(args)
            if args[:2]==('release','download'):
                Path(args[args.index('--dir')+1],publisher.NAME).write_bytes(content)
            return ''
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);(path/publisher.NAME).write_bytes(content)
            (path/'SHA256SUMS').write_text(hashlib.sha256(content).hexdigest()+'  '+publisher.NAME+'\n')
            with patch.object(publisher,'gh',gh):publisher.publish(path)
        self.assertTrue(any(call[:2]==('release','edit') for call in calls))
        self.assertTrue(all('v1.6' not in call and 'v1.0.5' not in call for call in calls))

    def test_wrong_local_checksum_prevents_any_release_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);(path/publisher.NAME).write_bytes(b'bad-file');(path/'SHA256SUMS').write_text('wrong')
            with patch.object(publisher,'gh') as gh,self.assertRaises(ValueError):publisher.publish(path)
            gh.assert_not_called()
